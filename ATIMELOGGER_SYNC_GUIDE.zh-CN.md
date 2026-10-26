# Google Calendar 同步到 aTimeLogger Pro：完整配置与使用指南

本文档说明如何在不依赖 Codex 的情况下，使用本项目把一个或多个 Google Calendar 日历同步到 aTimeLogger Pro。

## 1. 功能概览

本同步工具支持：

- 从 Google Calendar 私密 iCal 地址读取日历事件。
- 同时管理和同步多个 Google Calendar 日历。
- 手动选择任意日期进行同步。
- 同步从指定日期开始的连续 7 天。
- 快速选择今天、昨天、本周、上周、最近 7 天等日期范围。
- 自动展开 Google Calendar 的重复日程。
- 跳过全天事件和已取消事件。
- 把日历事件写入指定的 aTimeLogger 活动类型。
- 自动查重，重复运行时不会重复导入相同事件。
- Windows 和 Linux 后台自动同步。
- 登录系统后自动同步、打开程序时自动同步、固定时间和固定频率同步。
- 在本地日志中保存后台同步结果。

本工具不需要 Codex、ChatGPT 或其他 AI 服务参与日常运行。

## 2. 同步后的记录内容

每个 Google Calendar 事件会创建为一条已经停止的 aTimeLogger 活动记录，使用日历事件原本的开始和结束时间。

aTimeLogger 备注中会包含类似内容：

```text
Google Calendar: 语文（5班）
Calendar: 课程表
Google Calendar Event ID: default:事件ID#事件开始时间
```

如果日历事件包含地点，备注中也会写入地点。

## 3. 查重规则

工具使用两种方式避免重复导入：

1. 优先检查备注中的 `Google Calendar Event ID`。
2. 同时检查活动类型、标题、开始时间和结束时间是否完全一致。

因此，可以安全地重复同步同一天或同一周。已经同步过的记录会计入 `skipped`，不会再次创建。

注意：

- 如果手动删除 aTimeLogger 中的记录，再次同步时通常会重新创建。
- 如果修改了 Google Calendar 事件的时间，可能会被视为新的事件实例。
- 不同日历中标题和时间完全相同的事件，精确时间查重规则可能把第二条识别为重复。

## 4. 支持的平台

### Windows

支持：

- Windows 10
- Windows 11
- Windows Server 桌面环境，前提是已安装 Python、Node.js 和 npm

自动同步使用：

- Windows 计划任务：固定时间运行。
- 当前用户本地定时器：Windows 拒绝创建计划任务时自动启用，无需管理员权限。
- Windows 登录启动项：登录桌面后运行。

### Linux

支持带桌面环境且具有用户级 `systemd` 的常见 Linux 发行版，例如：

- Ubuntu
- Debian
- Linux Mint
- Fedora
- Arch Linux

自动同步使用：

- 用户级 `systemd` timer：固定时间运行。
- XDG Autostart：登录桌面后运行。

Linux 图形界面需要 Tk。Ubuntu/Debian 可安装：

```bash
sudo apt install python3-tk
```

### 不支持或未验证的平台

- macOS 当前未实现自动同步配置。
- 没有桌面环境的 Linux 无法打开图形界面，但可以直接运行底层命令。
- 容器、NAS 和服务器环境需要自行配置 cron 或 systemd 服务。

## 5. 运行环境

建议安装：

- Python 3.10 或更高版本。
- Node.js 20 或更高版本。
- npm。
- 可访问 Google Calendar 和 `https://app.atimelogger.pro` 的网络。

检查环境：

```bash
python --version
node --version
npm --version
```

Linux 有时需要使用：

```bash
python3 --version
```

首次安装项目依赖：

```bash
npm install
```

## 6. 必须保留的文件

建议完整保留整个项目文件夹。同步功能主要依赖以下文件：

| 文件 | 用途 |
| --- | --- |
| `.dev.vars` | 保存默认日历、aTimeLogger 登录信息和主要配置 |
| `.atimelogger-calendars.json` | 保存附加日历及已选择的日历 |
| `.atimelogger-sync-settings.json` | 保存自动同步频率和界面设置 |
| `scripts/sync-google-calendar-to-atimelogger.mjs` | 实际执行同步的核心脚本 |
| `run_atimelogger_sync_choose_date.pyw` | Windows 图形界面入口 |
| `run_atimelogger_sync_choose_date.py` | Linux 图形界面入口 |
| `run_atimelogger_sync_silent.pyw` | 后台静默同步入口 |
| `atimelogger_automation.py` | Windows/Linux 自动同步管理 |
| `atimelogger_calendars.py` | 多日历配置管理 |
| `package.json` 和 `package-lock.json` | Node.js 依赖定义 |

`node_modules` 可以重新通过 `npm install` 生成，不一定需要备份。

## 7. 准备 Google Calendar 私密 iCal 地址

在 Google Calendar 网页中：

1. 打开 Google Calendar 设置。
2. 找到要同步的日历。
3. 打开该日历的设置或“集成日历”区域。
4. 找到“iCal 格式的私密地址”。
5. 保存该地址。

私密 iCal 地址通常类似：

```text
https://calendar.google.com/calendar/ical/.../private-.../basic.ics
```

安全提示：

- 私密 iCal 地址相当于该日历的只读访问密码。
- 不要公开发布，不要提交到 Git。
- 如果地址泄露，请在 Google Calendar 中重置私密地址，并更新本地配置。

## 8. 配置 aTimeLogger 登录信息

你只需要知道：

- aTimeLogger Pro 登录账号。
- aTimeLogger Pro 登录密码。
- Google Calendar 私密 iCal 地址。

在项目目录的 `.dev.vars` 文件中添加或更新：

```env
GOOGLE_CALENDAR_ICS_URL=你的Google日历私密iCal地址
SYNC_TIMEZONE=Asia/Shanghai

ATIMELOGGER_BASE_URL=https://app.atimelogger.pro
ATIMELOGGER_USERNAME=你的aTimeLogger账号
ATIMELOGGER_PASSWORD=你的aTimeLogger密码
ATIMELOGGER_ACTIVITY_TYPE_NAME=工作

ATIMELOGGER_DRY_RUN=false
```

配置规则：

- 每行使用 `名称=值`。
- 等号左右不要添加多余空格。
- 不要把真实密码或 iCal 地址复制到公开位置。
- 修改 aTimeLogger 密码后，需要同步更新 `.dev.vars`。

### 使用令牌登录

如果已经有 aTimeLogger Bearer token，也可以使用：

```env
ATIMELOGGER_TOKEN=你的令牌
```

如果同时配置了 token 和账号密码，工具优先使用 token。

token 可能过期。长期使用通常更适合配置账号和密码，由脚本每次运行时登录并获取临时令牌。

### 完整配置项参考

| 配置项 | 是否必需 | 说明 |
| --- | --- | --- |
| `GOOGLE_CALENDAR_ICS_URL` | 通常必需 | 默认课程表的 Google Calendar 私密 iCal 地址 |
| `GOOGLE_CALENDAR_ICS_FILE` | 可选 | 从本地 ICS 文件读取默认日历；配置后优先于 `GOOGLE_CALENDAR_ICS_URL` |
| `SYNC_TIMEZONE` | 可选 | 同步日期使用的时区，默认 `Asia/Shanghai` |
| `ATIMELOGGER_BASE_URL` | 可选 | aTimeLogger 服务地址，默认 `https://app.atimelogger.pro` |
| `ATIMELOGGER_ACTIVITY_TYPE_NAME` | 可选 | 写入的活动类型或分组名称，默认 `工作` |
| `ATIMELOGGER_USERNAME` | 条件必需 | 未配置 token 时使用的登录账号 |
| `ATIMELOGGER_PASSWORD` | 条件必需 | 未配置 token 时使用的登录密码 |
| `ATIMELOGGER_TOKEN` | 可选 | Bearer token；配置后优先于账号密码 |
| `ATIMELOGGER_CONFIG_JSON` | 可选 | 可包含 `token` 的 JSON 配置；优先级低于 `ATIMELOGGER_TOKEN` |
| `ATIMELOGGER_DRY_RUN` | 可选 | `true` 表示只检查不写入，其他值按实际同步处理 |

配置加载优先级从高到低：

1. 启动脚本前已经存在的系统环境变量。
2. 项目目录中的 `.dev.vars`。
3. 项目目录中的 `.env`。

登录方式优先级从高到低：

1. `ATIMELOGGER_TOKEN`
2. `ATIMELOGGER_CONFIG_JSON` 中的 token
3. `ATIMELOGGER_USERNAME` 和 `ATIMELOGGER_PASSWORD`

同一个配置项不要在文件中重复写多次。脚本会优先使用最先加载到的值，后面的重复配置不会覆盖前面的值。

## 9. 配置 aTimeLogger 活动类型

配置项：

```env
ATIMELOGGER_ACTIVITY_TYPE_NAME=工作
```

如果填写的是具体可记录活动，例如：

```env
ATIMELOGGER_ACTIVITY_TYPE_NAME=授课
```

所有同步事件会写入该具体活动。

如果填写的是分组，例如 `工作`，工具会自动选择该分组下排序最前的可写活动。

重要说明：

- 分组本身不能创建活动记录。
- 如果希望固定写入某个子活动，请填写具体活动名称。
- 当前所有选中的 Google Calendar 都会写入同一个 aTimeLogger 活动类型。
- 当前版本不支持为每个 Google Calendar 分别映射不同的 aTimeLogger 活动类型。

## 10. 测试模式

测试模式只读取和检查，不写入 aTimeLogger：

```env
ATIMELOGGER_DRY_RUN=true
```

实际同步：

```env
ATIMELOGGER_DRY_RUN=false
```

也可以临时从命令行执行测试：

```bash
npm run sync:atimelogger-calendar -- --dry-run
```

建议首次配置或修改日历后，先使用测试模式确认结果。

## 11. 使用图形界面

### Windows

双击：

```text
run_atimelogger_sync_choose_date.pyw
```

### Linux

在项目目录运行：

```bash
python3 run_atimelogger_sync_choose_date.py
```

程序包含三个页面：

1. `手动同步`
2. `日历`
3. `自动同步`

## 12. 手动同步页面

手动同步页面支持：

- 同步单日。
- 从指定日期开始同步连续 7 天。
- 今天。
- 昨天。
- 一周前。
- 一个月前。
- 本周，按周一至周日计算。
- 上周，按周一至周日计算。
- 最近 7 天。
- 手动输入任意 `YYYY-MM-DD` 日期。

使用步骤：

1. 先在“日历”页面选择需要同步的日历。
2. 打开“手动同步”页面。
3. 选择单日或连续 7 天。
4. 选择快捷日期或输入日期。
5. 点击“开始同步”。
6. 等待结果弹窗。

## 13. 多日历配置

默认课程表从 `.dev.vars` 中读取：

```env
GOOGLE_CALENDAR_ICS_URL=默认课程表私密iCal地址
```

添加其他日历：

1. 打开“日历”页面。
2. 输入新日历名称。
3. 输入该日历的 Google Calendar 私密 iCal 地址。
4. 点击“添加日历”。
5. 勾选或多选需要同步的日历。
6. 点击“保存日历选择”。

支持：

- 全选日历。
- 取消选择。
- 重命名附加日历。
- 删除附加日历。

附加日历保存在：

```text
.atimelogger-calendars.json
```

该文件包含私密 iCal 地址，必须安全保管。

## 14. 自动同步页面

自动同步完全在本地运行，不依赖 Codex。

### 登录系统后自动同步今天

启用后：

- Windows：用户登录桌面后运行。
- Linux：桌面登录后通过 XDG Autostart 运行。

它不是严格意义上的“电脑通电后立即运行”。如果电脑开机后一直停留在登录界面，不会运行。

### 打开本脚本时自动同步今天

启用后，每次打开图形界面都会自动同步当天。

### 固定时间自动同步

支持：

- 每天。
- 每隔 2 天。
- 每隔 7 天。
- 每周固定一天。
- 设置固定运行时间。

自动任务每次只同步运行当天。补同步历史日期或整周，请使用“手动同步”页面。

在第二版中，自动同步内容可以独立选择 `Google Calendar → aTimeLogger`、`Toggl → aTimeLogger` 和 `aTimeLogger → Toggl`。两个 Toggl 方向同时选择时等同于自动双向同步。

### Windows 自动同步限制

- 电脑必须开机。
- 当前用户通常需要登录。
- 电脑休眠期间任务可能无法按时运行。
- 移动项目文件夹后，需要重新保存自动同步设置。
- 如果 Windows 拒绝创建计划任务，程序会自动改用当前用户本地定时器，并在自动同步页面显示实际使用的方式。

### Linux 自动同步限制

- 固定时间任务使用用户级 `systemd` timer。
- 登录启动使用 XDG Autostart。
- 默认情况下，用户级服务通常在用户登录后可用。
- 如果希望未登录时也运行，需要管理员执行用户 lingering 配置，例如：

```bash
sudo loginctl enable-linger 你的Linux用户名
```

该操作属于系统级设置，请确认了解安全影响后再使用。

## 15. 命令行使用

同步今天：

```bash
npm run sync:atimelogger-calendar
```

同步指定日期：

```bash
npm run sync:atimelogger-calendar -- --date 2026-06-13
```

测试指定日期，不写入：

```bash
npm run sync:atimelogger-calendar -- --date 2026-06-13 --dry-run
```

通过内部日历 ID 筛选日历：

```bash
npm run sync:atimelogger-calendar -- --date 2026-06-13 --calendars default
```

通常不需要手动使用日历 ID。图形界面会自动管理日历选择。

## 16. 后台同步日志

自动同步日志位于：

```text
logs/atimelogger-auto-sync.log
```

示例：

```text
[2026-06-13T18:23:08+08:00] exit=0 {"date":"2026-06-13","calendars":["课程表"],"calendarEvents":4,"created":2,"skipped":2,"failed":0,"dryRun":false}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `exit` | `0` 表示脚本正常结束，非 `0` 表示运行失败 |
| `date` | 同步日期 |
| `calendars` | 本次使用的日历 |
| `calendarEvents` | 读取到的日历事件数量 |
| `created` | 新创建的 aTimeLogger 记录数量 |
| `skipped` | 因测试模式或重复而跳过的数量 |
| `failed` | 写入失败的数量 |
| `dryRun` | 是否为测试模式 |

日志超过约 2 MB 后会轮换为上一份日志。

## 17. 备份与迁移到新电脑

推荐备份整个项目文件夹。

至少备份：

```text
.dev.vars
.atimelogger-calendars.json
.atimelogger-sync-settings.json
package.json
package-lock.json
scripts/
所有 Python 和 Pythonw 文件
```

迁移步骤：

1. 把项目文件夹复制到新电脑。
2. 安装 Python、Node.js 和 npm。
3. 在项目目录运行：

```bash
npm install
```

4. 测试：

```bash
npm run sync:atimelogger-calendar -- --dry-run
```

5. 打开图形界面。
6. 在“自动同步”页面重新保存自动同步设置。

自动任务包含项目绝对路径，所以移动目录或迁移电脑后必须重新保存。

## 18. 安全建议

以下文件包含敏感信息：

```text
.dev.vars
.atimelogger-calendars.json
```

安全建议：

- 不要通过公开聊天、邮件或代码仓库发送这些文件。
- 不要提交到 Git。
- 为电脑账户设置密码。
- 对备份文件进行加密。
- 如果 iCal 地址泄露，在 Google Calendar 中重置地址。
- 如果 aTimeLogger 密码泄露，立即修改密码并更新 `.dev.vars`。

项目的 `.gitignore` 已忽略敏感配置和日志，但仍应在提交代码前检查。

## 19. 常见故障

### 提示缺少 `GOOGLE_CALENDAR_ICS_URL`

检查 `.dev.vars` 是否包含：

```env
GOOGLE_CALENDAR_ICS_URL=完整的私密iCal地址
```

### 提示 aTimeLogger 登录失败

检查：

- 账号和密码是否正确。
- 是否修改过密码。
- `.dev.vars` 是否有多行重复配置。
- 是否有已过期的 `ATIMELOGGER_TOKEN` 覆盖账号密码登录。

如果不需要 token，可以删除或注释：

```env
ATIMELOGGER_TOKEN=...
```

### 提示分组不能作为活动类型

把 `ATIMELOGGER_ACTIVITY_TYPE_NAME` 改成具体可写活动名称，例如：

```env
ATIMELOGGER_ACTIVITY_TYPE_NAME=授课
```

当前脚本会自动解析分组，但指定具体类型最稳定。

### 同步结果全部是 `skipped`

常见原因：

- 这些事件已经同步过。
- 当前开启了测试模式。

检查：

```env
ATIMELOGGER_DRY_RUN=false
```

### 自动同步没有运行

检查：

- 电脑是否开机并联网。
- 用户是否已登录。
- 项目文件夹是否被移动。
- Python、Node.js 和 npm 是否仍然存在。
- `logs/atimelogger-auto-sync.log` 中是否有错误。
- 自动同步页面中任务状态是否已启用。

### Linux 图形界面无法打开

安装 Tk：

```bash
sudo apt install python3-tk
```

然后运行：

```bash
python3 run_atimelogger_sync_choose_date.py
```

### Linux 自动同步找不到 npm

确认：

```bash
command -v npm
npm --version
```

如果 npm 仅通过 nvm 安装，用户级 systemd 可能无法自动读取 nvm 环境。可安装系统级 Node.js/npm，或自行修改用户级 systemd 服务的环境配置。

## 20. 已知限制

- 所有选中的日历统一写入同一个 aTimeLogger 活动类型。
- 不支持把每个日历映射到不同活动类型。
- 不同步全天事件。
- 不同步已取消事件。
- 不会自动删除已从 Google Calendar 删除的 aTimeLogger 记录。
- 修改 Google Calendar 已同步事件后，不会自动修改旧的 aTimeLogger 记录，可能会新建一条。
- 工具依赖 aTimeLogger 当前网页接口；如果 aTimeLogger 将来修改接口，脚本可能需要更新。
- 私密 iCal 日历是只读数据源，Google Calendar 的更新可能存在短暂延迟。

## 21. 完全不使用 Codex 是否可以继续运行

可以。

只要保留项目文件，并确保以下内容可用，工具就能继续运行：

- aTimeLogger 账号和密码，或有效 token。
- Google Calendar 私密 iCal 地址。
- Python。
- Node.js 和 npm。
- 已安装的 Node.js 依赖。
- 正确配置的本地自动任务。

Codex 仅用于帮助创建和维护脚本，不参与日常同步。
