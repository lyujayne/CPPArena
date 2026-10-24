# PyPI 发布

本目录包含现有 v2.9 的独立 pip 封装。仅封装和发布已有应用，不修改算法或主程序路径逻辑，主平台版本仍为 2.9。项目整体许可证为 GPL-3.0-or-later，见 LICENSE；第三方声明见 NOTICE。

2026-10-22 已正式发布到 [PyPI cpp-arena 2.9](https://pypi.org/project/cpp-arena/2.9/)，wheel 和源码发行包均上传成功，已通过 PyPI JSON API 核对两个公开文件的 SHA256 与本地验证产物一致。另从正式 PyPI 索引以禁用缓存的方式下载并试装成功，`python -m cpp_arena --version` 返回 `2.9`；试装复用本机已验证的运行依赖。

发布前验证：两个包均通过 `twine check --strict`；pip 安装后在源码目录外启动主窗口及独立历史平台成功；HM/Greene 原生库、spawn 独立算法任务及含 JPEG/KML 的完整实验导出通过。发行包共收录 122 个应用文件（97 个 Python 源文件），已核对排除本机数据，wheel 与源码包的应用快照一致。

包名为 `cpp-arena`，构建产物为 `cpp_arena-2.9-py3-none-win_amd64.whl` 和 `cpp_arena-2.9.tar.gz`。完整功能支持 Windows x64、64 位 Python 3.10+。安装命令为 `python -m pip install cpp-arena==2.9`。

安装后执行 `cpp-arena` 或 `python -m cpp_arena` 启动主程序，`cpp-arena-history` 启动独立历史平台。首次启动将现有应用释放到 `%LOCALAPPDATA%\CPP Arena\2.9`，设置和数据保存在这个可写目录；可提前设置环境变量 `CPP_ARENA_HOME` 更改父目录。每个版本使用独立目录，升级不自动迁移旧记录，可通过历史平台导入；卸载 pip 包后数据目录仍保留。

构建工具使用 Python 3.11+。在源码根目录执行：

```powershell
python -m pip install "setuptools>=77" wheel build twine
python packaging/pypi/build_release.py
python -m twine check --strict pypi-dist/cpp_arena-2.9-py3-none-win_amd64.whl pypi-dist/cpp_arena-2.9.tar.gz
```

构建会先生成源码发行包，再从该发行包构建 wheel。程序源码收录在 `cpp_arena/application.zip` 中，包含独立历史平台、原生库源码和构建说明。不会收录本机实验记录、数据集库、工程、设置、导出图片、旧 exe 或临时文件。

正式上传需要在 PyPI 账号中完成邮箱验证和双重认证，并创建 API token。凭据可配置在用户自己的 `.pypirc` 或系统凭据管理器中；不要提交到项目中。默认上传地址为正式 PyPI：

```powershell
python -m twine upload pypi-dist/cpp_arena-2.9-py3-none-win_amd64.whl pypi-dist/cpp_arena-2.9.tar.gz
```

Twine 提示用户名时填写 `__token__`，密码处粘贴 PyPI API token。首次发布尚不存在的新项目时，需要允许创建项目的账号级 token，发布成功后可换成项目专用 token。

如需让后续发布命令直接使用本机凭据，可在 `C:\Users\32636\.pypirc` 中保存以下配置，将占位内容替换为真实 Token；不要把真实 Token 发到聊天或提交到 Git：

```ini
[distutils]
index-servers = pypi

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = 在此填写本机的真实PyPI令牌
```

Token 创建页面：[PyPI 账号设置](https://pypi.org/manage/account/token/)。配置好后即可继续上传，无需修改安装包。

上传后可在虚拟环境中执行 `python -m pip install --index-url https://pypi.org/simple cpp-arena==2.9` 并核对启动命令。后续修改程序需要按项目版本约定递增版本，不能覆盖已发布的 2.9 文件。

官方参考：[PyPA 打包指南](https://packaging.python.org/en/latest/tutorials/packaging-projects/)、[PyPI API token](https://pypi.org/help/#apitoken)、[CGAL 许可](https://www.cgal.org/license.html)。
