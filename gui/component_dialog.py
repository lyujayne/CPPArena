"""Import an independently composable module or save an implementation template."""
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout)
from config.default_params import COMPONENT_DIR
from core.component_plugins import component_template


class ComponentInstallDialog(QDialog):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle('新增分割方法' if kind == 'decomposition' else '新增路径规划算法')
        self.resize(760, 470)
        layout = QVBoxLayout(self)
        hint = QLabel('选择包含算法实现的 Python 文件。安装后将出现在独立模块列表，支持组合、参数设置和后台运行。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('选择 .py 实现文件')
        browse = QPushButton('选择文件')
        browse.clicked.connect(self.browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        example = QTextBrowser()
        example.setPlainText(component_template(kind))
        layout.addWidget(example, 1)
        template = QPushButton('另存接口模板（修改实现后导入）')
        template.clicked.connect(self.save_template)
        layout.addWidget(template)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('安装模块')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择算法实现', COMPONENT_DIR, 'Python (*.py)')
        if path:
            self.path_edit.setText(path)

    def validate(self):
        if Path(self.path_edit.text()).is_file() and self.path_edit.text().lower().endswith('.py'):
            self.accept()
        else:
            QMessageBox.warning(self, '未选择实现', '请选择有效的 Python 实现文件。')

    def save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存算法接口模板', 'custom_' + self.kind + '.py', 'Python (*.py)')
        if path:
            Path(path).write_text(component_template(self.kind), encoding='utf-8')
            self.path_edit.setText(path)
