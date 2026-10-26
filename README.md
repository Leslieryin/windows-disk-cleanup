# windows-disk-cleanup

Windows 磁盘清理工具。**分层、可预演、默认只读。**

清缓存这件事本身不难，难的是"删错了怎么办"。所以这个工具的第一条设计原则不是"能清多少"，而是**每次动手之前你都清楚地知道要删什么、为什么可以删**。

```bash
python cleanup.py scan                      # 默认命令，只扫描出报告，一个字节都不删
python cleanup.py clean --level safe --dry-run   # 预演：告诉你将释放多少
python cleanup.py clean --level safe        # 真删，只删纯缓存
```

![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.9%2B-3776AB)
![platform](https://img.shields.io/badge/platform-Windows-0078D4)
![deps](https://img.shields.io/badge/dependencies-none%2C%20stdlib%20only-2ea44f)

纯标准库，不需要 `pip install` 任何东西。

---

## 安全模型

规则按「删掉会不会丢东西」分三级，不是按"能腾出多少空间"排的：

| 等级 | 含义 | 典型内容 | 默认行为 |
|---|---|---|---|
| `safe` | 纯缓存，删了立刻重新生成，无副作用 | 用户 Temp、浏览器 Cache/Code Cache、npm/pip 缓存、缩略图缓存 | `clean --level safe` 可清 |
| `caution` | 系统/驱动缓存，会重建但**暂时变慢** | NVIDIA 着色器缓存、DirectX 缓存、Prefetch | 需要显式 `--level caution` |
| `risky` | 涉及系统服务，文件常被占用 | `%WINDIR%\Temp`、`%WINDIR%\Logs`、Windows 更新下载缓存 | 需要 `--level risky --yes` 双确认 |

几个刻意的设计：

**默认动作是 `scan`，不是 `clean`。** 不带参数直接运行只会扫描出报告。想删东西必须写出 `clean` 并指明等级——不存在"手滑跑一下就删了"的情况。

**`risky` 要两次确认。** 光写 `--level risky` 不够，还得加 `--yes`。这个等级会碰 Windows 更新缓存，而多数文件被 `wuauserv` 服务占着，工具**不会替你停服务**，只会跳过占用文件。

**路径有白名单。** 每个清理目标都必须在 `%LOCALAPPDATA%`、`%APPDATA%`、`%TEMP%`、`%WINDIR%`、`%PROGRAMDATA%` 之下，否则拒绝执行。这样即使规则表被改坏，也指不到你的文档目录上。同一道闸还会拦下：盘符根目录、含 `.git` 的路径、用户主目录本身。

**只有缩略图缓存是"部分清理"。** `%LOCALAPPDATA%\Microsoft\Windows\Explorer` 这个目录里除了 `thumbcache_*.db`，还存着窗口布局和视图设置。规则用 glob 只匹配缓存文件，目录里其余内容原样保留——整个目录端掉会让资源管理器重置。

## 明确不碰的东西

| 目标 | 为什么不动 |
|---|---|
| 回收站（`$Recycle.Bin`） | 里面是你删过的文件。清缓存和"替你决定永久丢弃"是两回事 |
| 文档 / 桌面 / 图片 / 视频 | 用户数据，不属于缓存 |
| `node_modules` / `.git` / `venv` | 项目工作区，删了要重装或丢历史 |
| `%WINDIR%` 下除 Temp/Logs/SoftwareDistribution 外的目录 | 系统组件，误删代价过高 |

想清回收站，用系统自带的「磁盘清理」或资源管理器——那个操作有系统级的二次确认，比任何第三方脚本都更该由你自己点。

## 命令参考

### scan —— 扫描（默认）

```bash
python cleanup.py scan                          # 扫全部等级
python cleanup.py scan --level safe             # 只看安全级
python cleanup.py scan --out reports            # 报告输出目录，默认 cleanup-reports/
```

真实运行输出：

```
等级      项目                             文件数          大小  路径
--------------------------------------------------------------------------------
safe    用户临时文件                        1213    120.7 MB  C:\Users\<you>\AppData\Local\Temp
safe    Edge 网页缓存                      791    218.6 MB  ...\Edge\User Data\Default\Cache
safe    npm 缓存                        1526    149.7 MB  ...\npm-cache
safe    资源管理器缩略图缓存                      30    119.3 MB  ...\Windows\Explorer
...
--------------------------------------------------------------------------------
合计 11 个位置，4897 个文件，688.5 MB
```

### clean —— 执行清理

```bash
python cleanup.py clean --level safe --dry-run   # 预演，只统计
python cleanup.py clean --level safe             # 执行
python cleanup.py clean --level caution          # + 驱动/预读取缓存
python cleanup.py clean --level risky --yes      # + 系统缓存
```

被占用或无权限的文件会自动跳过，不影响其他文件。每次执行都会在 `cleanup-reports/` 留下带时间戳的 Markdown 报告，其中列出释放量、跳过数与失败样本。

### bigfiles —— 大文件报告

```bash
python cleanup.py bigfiles --min-mb 500 --top 30
python cleanup.py bigfiles --root "D:\" --min-mb 1024
```

递归扫描用户目录，列出超过阈值的文件并按大小排序，标注类型（视频 / 镜像安装包 / 模型权重 / 虚拟机备份 / 音频）。**只列出，不删除。**

### media —— 旧媒体占用报告

```bash
python cleanup.py media --older-than-years 2
python cleanup.py media --root "E:\videos"
```

按年份聚合视频、音频、图片的占用，标出早于 N 年的总量。**只统计，不删除。**

媒体文件通常是独一份，删了就没有了，而且年份判定依赖文件修改时间会出错。这个命令的价值在于让你看见"三年前的录像占了 200 GB"这件事，至于删不删、删哪些，交给资源管理器更合适。

## 实现细节

**短路径陷阱。** `%TEMP%` 常展开成 `C:\Users\LESLIE~1\AppData\Local\Temp` 这种 8.3 短名，而 `%LOCALAPPDATA%\Temp` 是长名。两者是同一个目录，字符串却不相等——不去重就会把同一个 Temp 目录统计两遍（实测会虚报 120 MB）。`rules.expand()` 统一走 `os.path.realpath()` 解析，再按规范化路径去重。

**删除顺序。** 未过滤的规则用 `os.walk(topdown=False)` 自底向上，先删文件再 `rmdir` 空目录，根目录本身保留——下次扫描还能认出这个目标。

**符号链接不跟随。** 统计和删除都用 `os.lstat()`，不会顺着链接跑到别的盘上去。

**规则是数据。** 新增一个清理目标只需在 `rules.py` 的 `RULES` 里加一行，不用改任何执行逻辑。

## 测试

```bash
python tests/test_rules.py
```

18 个用例，覆盖等级过滤、环境变量展开、文件类型归类、Markdown 表格对齐、以及 `guard()` 的每一条拒绝规则。测试不触碰真实文件。

## 兼容性

- Windows 10 / 11
- Python 3.9+（只用标准库）
- 不需要管理员权限。**部分文件需要提权才能删**，工具会跳过并记入报告，不会静默失败

## 许可证

[MIT](LICENSE)
