"""Combination manager with independent parameters and live experiment log."""
from datetime import datetime
import time
import random
import re
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)
from core.combinations import (Combination, DECOMPOSITIONS, PLANNERS,
                               component_spec, enumerate_combinations)


class ExperimentPanel(QWidget):
    run_requested = Signal(str)
    stop_requested = Signal()
    export_requested = Signal()
    component_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.combinations = []
        self.datasets = []
        self._last_done = -1
        self._last_log_update = 0
        self._running = False
        self._configuration_controls = []
        self.algorithm_scrolls = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.configuration = QWidget()
        body = QVBoxLayout(self.configuration)
        body.setContentsMargins(0, 0, 0, 0)
        self.decomp_checks, self.planner_checks = {}, {}
        choices = QHBoxLayout()
        for title, catalog, target in (("① 选择分割方法", DECOMPOSITIONS, self.decomp_checks),
                                       ("② 选择路径规划", PLANNERS, self.planner_checks)):
            box = QGroupBox(title)
            box.setFixedHeight(210)
            box_layout = QVBoxLayout(box)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            host = QWidget()
            option_layout = QVBoxLayout(host)
            option_layout.setContentsMargins(4, 4, 4, 4)
            for key, (label, cls) in catalog.items():
                check = QCheckBox(label.replace('（', '\n（', 1))
                check.setToolTip(getattr(cls, 'description', ''))
                check.setChecked(not getattr(cls, 'independent_component_params', False))
                target[key] = check
                option_layout.addWidget(check)
            option_layout.addStretch(1)
            scroll.setWidget(host)
            box_layout.addWidget(scroll)
            self.algorithm_scrolls.append(scroll)
            choices.addWidget(box)
            if target is self.decomp_checks:
                self.decomposition_layout = option_layout
            else:
                self.planning_layout = option_layout
        body.addLayout(choices)
        module_row = QHBoxLayout()
        for text, kind in (('新增分割方法', 'decomposition'), ('新增路径规划算法', 'planning')):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, k=kind: self.component_requested.emit(k))
            self._configuration_controls.append(button)
            module_row.addWidget(button)
        body.addLayout(module_row)
        actions = QHBoxLayout()
        self.btn_enumerate = QPushButton("穷举组合")
        self.btn_enumerate.clicked.connect(self.enumerate)
        add = QPushButton("添加组合")
        add.clicked.connect(self.add_dialog)
        remove = QPushButton("删除所选")
        remove.clicked.connect(self.remove_selected)
        for button in (self.btn_enumerate, add, remove):
            self._configuration_controls.append(button)
            actions.addWidget(button)
        body.addLayout(actions)
        self.btn_all_datasets = QPushButton('统一设置所有组合的数据集')
        self.btn_all_datasets.setToolTip('将勾选的数据集应用到当前清单的全部组合，覆盖已有的逐行数据集设置。')
        self.btn_all_datasets.clicked.connect(lambda checked=False: self.edit_datasets())
        self._configuration_controls.append(self.btn_all_datasets)
        body.addWidget(self.btn_all_datasets)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["分割", "规划", "独立参数", "数据集"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalScrollBar().setSingleStep(24)
        body.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("种子"))
        self.seeds_edit = QLineEdit("42")
        self.seeds_edit.setToolTip("逗号分隔或区间，如 42,7 或 1-10；每组合对每个种子运行一次")
        row.addWidget(self.seeds_edit)
        random_button = QPushButton('随机多个')
        random_button.setToolTip('按下方数量生成互不重复的随机种子；生成后保留完整列表，可复现实验。')
        random_button.clicked.connect(self.randomize_seeds)
        row.addWidget(random_button)
        body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('随机数量'))
        self.random_seed_count = QSpinBox()
        self.random_seed_count.setRange(2, 1000)
        self.random_seed_count.setValue(10)
        row.addWidget(self.random_seed_count)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("当前数据集", "active")
        self.scope_combo.addItem("全部数据集", "all")
        row.addWidget(self.scope_combo)
        body.addLayout(row)
        self._configuration_controls.extend([self.seeds_edit, random_button, self.random_seed_count, self.scope_combo])
        layout.addWidget(self.configuration, 1)
        row = QHBoxLayout()
        self.btn_run = QPushButton("运行组合清单")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(lambda: self.run_requested.emit("combinations"))
        self.btn_stop = QPushButton("终止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_stop)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        log_box = QGroupBox("实验日志", self)
        self.log_box = log_box
        log_box.hide()
        log_box.setMaximumHeight(190)
        log_layout = QVBoxLayout(log_box)
        self.status_label = QLabel("就绪 · 请穷举或添加组合")
        self.status_label.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(10000)
        self.log.setMinimumHeight(100)
        log_layout.addWidget(self.status_label)
        log_layout.addWidget(self.log)
        row = QHBoxLayout()
        self.btn_export = QPushButton("完整导出实验")
        self.btn_export.clicked.connect(self.export_requested.emit)
        row.addWidget(self.btn_export)
        layout.addLayout(row)

    def enumerate(self):
        selected_d = [k for k, c in self.decomp_checks.items() if c.isChecked()]
        selected_p = [k for k, c in self.planner_checks.items() if c.isChecked()]
        if not selected_d or not selected_p:
            QMessageBox.warning(self, "选择模块", "请至少选择一种分割方法和一种规划算法。")
            return
        old = {(c.decomposition, c.planning): c for c in self.combinations}
        self.combinations = [old.get((c.decomposition, c.planning), c)
                             for c in enumerate_combinations(selected_d, selected_p)]
        self.refresh_table()
        self.status_label.setText(f'已列出 {len(self.combinations)} 个组合；运行时仅执行清单中保留的任务。')

    def refresh_table(self):
        self.table.setRowCount(len(self.combinations))
        for i, combo in enumerate(self.combinations):
            for j, text in enumerate((combo.decomposition, combo.planning)):
                item = QTableWidgetItem(text)
                item.setToolTip(combo.label)
                self.table.setItem(i, j, item)
            changes = []
            for title, kind, key, values in (
                    ('分割', 'decomposition', combo.decomposition, combo.decomposition_params),
                    ('规划', 'planning', combo.planning, combo.planning_params)):
                for name, label, typ, default in component_spec(kind, key):
                    value = values.get(name, default)
                    if value != default:
                        changes.append(f'{title} · {label}：{default} → {value}')
            button = QPushButton(f'已修改 {len(changes)} 项' if changes else '默认参数')
            if changes:
                button.setToolTip('点击设置此组合参数。与默认方案的差异（默认值 → 当前值）：\n' + '\n'.join(changes))
                button.setStyleSheet('QPushButton:enabled { color:#92400e; background:#fff7ed; border:1px solid #f59e0b; }')
            else:
                button.setToolTip('默认参数：分割与规划参数均与所选模块的默认方案一致。\n点击设置此组合参数。')
            button.clicked.connect(lambda checked=False, c=combo: self.edit_params(c))
            button.setEnabled(not self._running)
            self.table.setCellWidget(i, 2, button)
            datasets = QPushButton('全局范围' if combo.dataset_ids is None else f'{len(combo.dataset_ids)} 个数据集')
            datasets.setToolTip('为此组合独立勾选数据集；全局范围使用当前/全部数据集设置。')
            datasets.clicked.connect(lambda checked=False, c=combo: self.edit_datasets(c))
            datasets.setEnabled(not self._running)
            self.table.setCellWidget(i, 3, datasets)

    def set_datasets(self, datasets):
        self.datasets = list(datasets)

    def refresh_modules(self):
        for catalog, checks, layout in ((DECOMPOSITIONS, self.decomp_checks, self.decomposition_layout),
                                         (PLANNERS, self.planner_checks, self.planning_layout)):
            for key, (label, cls) in catalog.items():
                if key not in checks:
                    check = QCheckBox(label.replace('（', '\n（', 1))
                    check.setChecked(True)
                    layout.insertWidget(layout.count()-1, check)
                    check.setEnabled(not self._running)
                    checks[key] = check
                else:
                    checks[key].setText(label.replace('（', '\n（', 1))
                checks[key].setToolTip(getattr(cls, 'description', ''))

    def edit_datasets(self, combo=None):
        bulk = combo is None
        targets = self.combinations if bulk else [combo]
        if not targets:
            QMessageBox.information(self, '组合清单为空', '请先穷举或添加组合，再统一设置数据集。')
            return
        selected_ids = targets[0].dataset_ids
        if bulk and any(c.dataset_ids != selected_ids for c in targets):
            selected_ids = None
        dialog = QDialog(self)
        dialog.setWindowTitle('统一设置所有组合的数据集' if bulk else combo.label + ' · 选择数据集')
        dialog.resize(560, 430)
        layout = QVBoxLayout(dialog)
        if bulk:
            hint = QLabel(f'应用到当前清单的全部 {len(targets)} 个组合，覆盖已有的逐行数据集设置；应用后仍可逐行调整。')
            hint.setWordWrap(True)
            layout.addWidget(hint)
        inherit = QCheckBox('使用全局范围（当前 / 全部数据集）')
        inherit.setChecked(not bulk and selected_ids is None)
        layout.addWidget(inherit)
        listing = QListWidget()
        for ds in self.datasets:
            item = QListWidgetItem(ds.name)
            item.setData(Qt.UserRole, ds.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if selected_ids is None or ds.id in selected_ids else Qt.Unchecked)
            listing.addItem(item)
        listing.setEnabled(not inherit.isChecked())
        inherit.toggled.connect(lambda on: listing.setEnabled(not on))
        layout.addWidget(listing)
        if bulk:
            select_all = QCheckBox('全选 / 取消全选')
            select_all.setChecked(listing.count() > 0 and all(
                listing.item(i).checkState() == Qt.Checked for i in range(listing.count())))
            select_all.toggled.connect(lambda on: [listing.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
                                                   for i in range(listing.count())])
            inherit.toggled.connect(lambda on: select_all.setEnabled(not on))
            layout.addWidget(select_all)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if bulk:
            buttons.button(QDialogButtonBox.Ok).setText('应用到所有组合')
        def accept():
            ids = [listing.item(i).data(Qt.UserRole) for i in range(listing.count()) if listing.item(i).checkState() == Qt.Checked]
            if not inherit.isChecked() and not ids:
                QMessageBox.warning(dialog, '数据集为空', '请至少选择一个数据集。')
                return
            for target in targets:
                target.dataset_ids = None if inherit.isChecked() else list(ids)
            dialog.accept()
        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_table()
            if bulk:
                scope = '全局范围（当前 / 全部数据集）' if inherit.isChecked() else f'{len(targets[0].dataset_ids)} 个数据集'
                self.status_label.setText(f'已将 {len(targets)} 个组合统一设置为{scope}。')

    def add_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加组合（可重复添加，分别设置参数）")
        dialog.setMinimumSize(700, 420)
        dialog.resize(840, 490)
        form = QFormLayout(dialog)
        form.setContentsMargins(28, 24, 28, 24)
        form.setVerticalSpacing(24)
        form.addRow(QLabel('选择分割方法与路径规划算法；添加后可单独设置此组合参数。'))
        d, p = QComboBox(), QComboBox()
        d.setMinimumHeight(38)
        p.setMinimumHeight(38)
        for widget, catalog in ((d, DECOMPOSITIONS), (p, PLANNERS)):
            for key, (label, cls) in catalog.items():
                widget.addItem(label, key)
                widget.setItemData(widget.count()-1, getattr(cls, 'description', ''), Qt.ToolTipRole)
        form.addRow("分割方法", d)
        form.addRow("规划算法", p)
        detail = QLabel()
        detail.setWordWrap(True)
        detail.setMinimumHeight(105)
        detail.setStyleSheet('color:#475569;padding:8px;background:#f1f5f9;')
        def update_detail():
            detail.setText('分割：' + getattr(DECOMPOSITIONS[d.currentData()][1], 'description', '') +
                           '\n规划：' + getattr(PLANNERS[p.currentData()][1], 'description', ''))
        d.currentIndexChanged.connect(update_detail)
        p.currentIndexChanged.connect(update_detail)
        update_detail()
        form.addRow(detail)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('添加组合')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.combinations.append(Combination(d.currentData(), p.currentData()))
            self.refresh_table()

    def remove_selected(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            del self.combinations[row]
        self.refresh_table()

    def edit_params(self, combo):
        dialog = QDialog(self)
        dialog.setWindowTitle(combo.label + " · 参数仅对本组合生效")
        dialog.resize(520, 620)
        layout = QVBoxLayout(dialog)
        host = QWidget()
        form = QFormLayout(host)
        widgets = {}
        for kind, key, values in (("decomposition", combo.decomposition, combo.decomposition_params),
                                   ("planning", combo.planning, combo.planning_params)):
            form.addRow(QLabel("分割参数" if kind == "decomposition" else "规划参数"))
            catalog = DECOMPOSITIONS if kind == 'decomposition' else PLANNERS
            scope = QLabel(getattr(catalog[key][1], 'description', ''))
            scope.setWordWrap(True)
            form.addRow(scope)
            spec = component_spec(kind, key)
            if not spec:
                form.addRow(QLabel("此模块无可调参数"))
            for name, label, typ, default in spec:
                widget = QSpinBox() if typ == "int" else QDoubleSpinBox()
                widget.setRange(0 if typ == "int" else -1e9, 1000000 if typ == "int" else 1e9)
                if name == 'li_adjacency_mode':
                    widget.setRange(0, 1)
                if typ != "int":
                    widget.setDecimals(8)
                widget.setValue(values.get(name, default))
                widget.setProperty("defaultValue", default)
                widget.setToolTip(f'默认值：{default}')
                form.addRow(label, widget)
                widgets[(kind, name)] = widget
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        layout.addWidget(scroll)
        reset = QPushButton("恢复此组合默认参数")
        reset.clicked.connect(lambda: [w.setValue(w.property("defaultValue")) for w in widgets.values()])
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            combo.decomposition_params = {k: w.value() for (kind, k), w in widgets.items()
                                          if kind == "decomposition" and w.value() != w.property("defaultValue")}
            combo.planning_params = {k: w.value() for (kind, k), w in widgets.items()
                                      if kind == "planning" and w.value() != w.property("defaultValue")}
            self.refresh_table()

    def seeds(self):
        result = []
        try:
            for part in self.seeds_edit.text().replace("，", ",").split(","):
                if "-" in part:
                    a, b = map(int, part.split("-"))
                    if not 0 <= a <= b < 2**32 or b-a >= 1000:
                        raise ValueError()
                    result.extend(range(a, b+1))
                else:
                    result.append(int(part.strip()))
            if not result or len(result) > 1000 or any(s < 0 or s >= 2**32 for s in result):
                raise ValueError()
        except ValueError:
            raise ValueError("种子须为 0～4294967295 的整数，支持逗号或递增区间（最多1000个）。")
        return list(dict.fromkeys(result))

    def set_seeds_text(self, seeds):
        self.seeds_edit.setText(", ".join(map(str, seeds)))

    def mode(self):
        return "combinations"

    def set_mode(self, mode):
        pass  # Old projects open with the new workflow.

    def randomize_seeds(self):
        self.set_seeds_text(random.SystemRandom().sample(range(2**32), self.random_seed_count.value()))

    def append_log(self, message, error=None):
        if error is None:
            error = bool(re.search(r'失败|报错|错误|Error|Exception|Traceback', message, re.I))
        scrollbar = self.log.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum()-2
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#b91c1c' if error else '#22354b'))
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(f"{datetime.now():%H:%M:%S}  {message}", fmt)
        if follow:
            scrollbar.setValue(scrollbar.maximum())

    def set_running(self, running):
        self._running = running
        for widget in self._configuration_controls + list(self.decomp_checks.values()) + list(self.planner_checks.values()):
            widget.setEnabled(not running)
        for row in range(self.table.rowCount()):
            for col in (2, 3):
                self.table.cellWidget(row, col).setEnabled(not running)
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_export.setEnabled(not running)
        if running:
            self._last_done = -1
            self.log.clear()
            self.append_log("实验开始：按清单依次执行组合")

    def set_progress(self, done, total, msg=""):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status_label.setText(msg)
        if done != self._last_done or "启动计算进程" in msg or re.search(r'失败|报错|Error|Exception', msg, re.I):
            self.append_log(msg)
            self._last_log_update = time.monotonic()
        self._last_done = done
