# Ctrip Plan Description Filling

## PyInstaller 打包说明

安装打包依赖需要在项目根目录执行：

```bash
python3 -m pip install -r requirements.txt pyinstaller
```

必须使用根目录的 spec 打包；不要直接对 `.pyw` 入口执行 PyInstaller：

```bash
python3 -m PyInstaller --clean --noconfirm CtripPlanDescriptionFilling.spec
```

Windows 也可以把上述 `python3` 替换为 `py`。spec 会在构建阶段校验并显式收集
`workflow_common.py`；缺少该文件时会直接终止构建，不再生成启动后才报缺少模块的 EXE。

输出目录：

- Windows: `dist/CtripPlanDescriptionFilling.exe`
- macOS: `dist/CtripPlanDescriptionFilling.app`

当前 spec 在 Windows 上生成单文件 EXE，方便直接分发给没有 Python 环境的电脑。macOS 仍保留 app bundle，因为 PyQt6/Qt 插件在 macOS 上以 bundle 形式保留文件结构更稳定。

Windows 单文件 EXE 首次启动时会解压临时运行文件，启动速度可能比 `onedir` 慢；如果杀软拦截临时解压目录，需要将程序加入信任列表或改回 `onedir` 分发整个目录。

不会打包 `request_captures/`、`outputs/`、`backups/` 等运行数据目录。登录态和运行输出应继续由程序按当前用户系统路径读取或生成，避免把个人 cookie/认证信息固化进发布包。

Windows 登录态只保存在 `%APPDATA%\CtripPlanDescriptionFilling\auth\ctrip_cookie_header.txt`。程序不再读取旧项目的 `C:\ProgramData\TripDetailFilling\session_data.json`，也不再读取程序目录中的 `auth_plain/`。

### macOS 本地开发包

```bash
python3 scripts/build_macos.py --local
```

默认构建当前 Mac 的原生架构，并检查 Bundle 内所有 Mach-O 文件都包含目标架构，再执行签名校验和 8 秒启动烟测。Apple Silicon 产物为 `arm64`；Intel 产物应在 Intel Python/依赖环境中使用 `--arch x86_64` 另行构建。当前 NumPy wheel 是单架构，不能把产物伪装成 `universal2`。

本地模式使用 adhoc 签名，只用于当前 Mac 调试。它不能通过下载场景的 Gatekeeper，不得把 `dist/CtripPlanDescriptionFilling.app` 直接发给其他人。

### macOS 可分发发布包

首次发布前，需要在钥匙串安装有效的 `Developer ID Application` 证书，并保存 Apple 公证凭据：

```bash
security find-identity -v -p codesigning
xcrun notarytool store-credentials CtripPlanDescriptionFilling
```

发布时使用证书的完整名称和已保存的公证 profile：

```bash
export MACOS_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)'
export MACOS_NOTARY_PROFILE='CtripPlanDescriptionFilling'
python3 scripts/build_macos.py --release
```

release 流程会依次完成：PyInstaller Developer ID 签名及 Hardened Runtime、严格签名校验、目标架构检查、启动烟测、`notarytool` 公证、staple、Gatekeeper `spctl` 验收，最后生成（当前 Apple Silicon Mac）：

```text
dist/CtripPlanDescriptionFilling-macOS-arm64.zip
```

只分发这个最终 ZIP。脚本使用 `ditto` 保存 macOS Bundle 的符号链接和资源属性；不要使用普通压缩工具重新压缩，不要分发临时的 `*-notarization.zip`，也不要把 `xattr -d com.apple.quarantine` 当作发布修复。

当前构建产物的最低系统版本是 macOS 11。直接运行 PyInstaller 仍会生成 adhoc 包；正式发布必须走 `scripts/build_macos.py --release`，否则脚本无法保证 Gatekeeper 验收。

## 运营分发稳定性

- 默认请求间隔为 1 秒；可调整范围为 0.5-1 秒。
- 最大并行请求数为 10；翻译件管理默认并行为 1，批量任务需要提速时再手动调高。
- 程序不会打包登录态。启动后会自动在线校验本地登录态；有效时静默继续，缺失或失效时提示运营同事先在 Edge/Chrome 登录 Ctrip，再点击“刷新登录态”。网络异常会提示暂时无法校验，不会误报为登录失效。
- 运行配置、登录态、请求统计写入当前用户系统配置目录；输出报告默认写入当前用户下载目录。
- 批量传出前先执行预载/预览，确认没有 stale、error、verify_failed 后再传出。
- 传出失败时先导出报告，再根据日志中的产品 ID、语言、接口错误定位，不要重复无间隔重试。

## 产品编辑工作台

GUI 将产品编辑收敛到一个入口：`产品信息接口修改`。

- 产品名称走 ProductInfo 保存并回读验证。
- 底价走 PriceAndStock 保存、生效并用正式价格回读验证。
- 供应商套餐 ID、对接代码、套餐说明走 PackageInfo 保存并回读验证。
- 提交审核、导出报告、刷新登录态仍在同一个产品编辑页完成。

导出的修改模板是单 sheet 宽表，固定包含产品名称、底价、供应商套餐 ID、对接代码、套餐说明和套餐说明规则列。旧调价模板、旧产品信息模板、旧套餐/API 模板仍可从该入口导入预览；程序会按字段分流到对应接口对象，不会把整行直接写入单个接口。

## 自定义配置与首次使用

公开版本不附带公司业务工作簿、后台截图、接口抓包、供应商标识或实际成本价。

| 配置项 | 如何填写 |
|---|---|
| Ctrip 登录态 | 先在本机 Edge/Chrome 登录自己的有权限账号，再在 GUI 点击“刷新登录态”；不要提交 Cookie 文件 |
| `productId`、`packageId`、`resourceId` | 从自己账号的商品及套餐读取，填写 GUI/Excel 或 CLI 对应参数；示例数字为虚构占位值 |
| 供应商 ID | 对接配置工作台“供应商 ID”输入框，默认留空；填写自己的供应商 ID |
| 对接系统 ID（`connectNoId`） | 对接配置工作台“对接系统 ID”输入框，默认留空；从自己账号实际配置取得 |
| `vendorPackageId`、对接代码 | 填写自己的供应商套餐映射；`EXAMPLE_VENDOR_PACKAGE_ID` 必须替换 |
| 成本价格和库存 | 从自己的商品读取并确认；模板示例价格为虚构值，不可直接用于生产 |
| APN、流量规则、重置时间、提前安装条件 | 按供应商说明填写本地规格/详情模板，通用示例不代表任何实际产品 |
| 任务、详情、规格工作簿 | 在 GUI 下载对应空白模板，填好后选择本地文件导入；原有私人模板可继续在本地使用 |
| 请求间隔、并行请求数 | GUI 调整；批量写入前先预览核对目标商品和字段 |
| `MACOS_CODESIGN_IDENTITY`、`MACOS_NOTARY_PROFILE` | 仅正式 macOS 打包时，设置为自己的签名证书及公证凭据 profile |

运行入口：`python3 ctrip_package_intro_filling.pyw`。CLI 参数可用 `python3 ctrip_package_intro_filling.pyw --help` 查看。

本地业务工作簿、登录态、抓包和输出报告不应加入 Git。公开分支为全新提交历史，旧业务历史未继承；已有本地克隆请重新克隆，不要把旧分支推回公开仓库。

## 发布前验收

```bash
python3 -m unittest tests.test_request_stats tests.test_request_coalescing tests.test_translation_rules -v
python3 -m unittest tests.test_macos_packaging -v
python3 scripts/build_macos.py --local
```

Windows 运营分发以 `dist/CtripPlanDescriptionFilling.exe` 为准。macOS 验收只能证明 spec 结构可用，Windows 单文件行为仍需要在 Windows 机器上实测启动、刷新登录态、预载翻译件、导出报告。
