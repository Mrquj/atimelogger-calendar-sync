# 第二版：Toggl 与 aTimeLogger Pro 双向同步指南

第二版在第一版 Google Calendar 同步功能基础上，增加 Toggl Track 与 aTimeLogger Pro 双向同步。

## 支持的同步方向

- Toggl → aTimeLogger
- aTimeLogger → Toggl
- 双向同步

只同步已经结束的时间记录。正在计时、没有结束时间的记录会跳过。

## 防止重复和同步循环

第二版使用本地映射文件保存 Toggl 时间记录 ID 与 aTimeLogger 活动/区间 ID：

```text
.toggl-atimelogger-state.json
```

首次同步：

- Toggl 中未映射的记录会创建到 aTimeLogger。
- aTimeLogger 中未映射的记录会创建到 Toggl。
- 如果两端存在开始时间、结束时间和标题完全一致的记录，会直接建立映射，不重复创建。

后续同步：

- 只有 Toggl 发生变化：更新 aTimeLogger。
- 只有 aTimeLogger 发生变化：更新 Toggl。
- 两端都发生变化：记录为冲突并跳过，不自动覆盖任何一端。
- 两端都没有变化：跳过。

当前不会传播删除操作，避免误删另一端数据。

## 项目、客户和标签映射

aTimeLogger 没有与 Toggl 完全对应的原生“项目”和“客户”字段，因此第二版按以下规则保留数据：

| Toggl 字段 | aTimeLogger 中的保存位置 |
| --- | --- |
| 描述 | 活动备注中的 `Toggl:` 行 |
| 项目名称 | 活动备注中的 `Toggl Project:` 行 |
| 项目 ID | 活动备注中的 `Toggl Project ID:` 行，用于回传时恢复项目 |
| 客户名称 | 活动备注中的 `Toggl Client:` 行 |
| 标签 | aTimeLogger 原生标签，同时显示在 `Toggl Tags:` 行 |

aTimeLogger → Toggl 时，aTimeLogger 原生标签会同步到 Toggl 标签。记录备注中保留了 `Toggl Project ID:` 时，回传到 Toggl 会恢复该项目；客户由 Toggl 项目关联自动恢复。

所有 Toggl 记录仍会导入到界面配置的 aTimeLogger 活动类型，例如 `工作`。项目和客户不会自动创建成新的 aTimeLogger 活动类型。

某条 Toggl 源记录本身没有项目、客户或标签时，aTimeLogger 中不会为该字段生成空内容。升级到此功能后的首次真实同步会自动补全旧映射记录的项目、客户和标签元数据。

更改 `Toggl → aTimeLogger 活动类型` 后，下一次 Toggl → aTimeLogger 或双向真实同步会把已有 Toggl 来源记录迁移到新的目标活动类型。只会迁移带有 Toggl 来源标记的记录，不会移动原本由 aTimeLogger 创建的记录。

`Toggl → aTimeLogger 活动类型` 只在同步方向为 `Toggl → aTimeLogger` 或 `双向同步` 时生效。如果方向选成 `aTimeLogger → Toggl`，不会从 Toggl 导入或迁移记录。保存配置时界面会明确显示当前方向和目标活动类型。

如果 Toggl 返回 HTTP 402 和 `hourly limit`，表示当前账户的 Toggl API 每小时调用额度已用完。等待返回信息中的倒计时结束后再运行；这与 aTimeLogger 活动类型配置无关。

## Toggl 来源过滤

`Toggl 双向同步` 页面可以选择：

- `全部已完成记录`：不根据来源过滤。
- `排除日历来源记录`：排除 Toggl 来源字段中包含日历关键词的记录。
- `仅手动/非集成记录`：排除日历来源记录，并排除带外部集成标识的记录。

Toggl API 没有统一可靠的“手动记录”布尔字段，因此“仅手动/非集成记录”通过以下字段判断：

- `created_with`
- `event_metadata.origin_feature`
- `integration_ext_type`
- `integration_ext_id`
- `integration_provider`

默认日历来源关键词：

```text
calendar,google calendar,outlook,ical
```

你可以在界面中修改关键词，以匹配自己 Toggl 账户实际返回的来源名称。

## 同步前重复检查

Toggl → aTimeLogger 创建新记录前，可以选择：

- `不检查重复`
- `同标题且时间完全一致`
- `同标题且时间有重叠`

完全一致的记录会建立本地映射，后续可以继续双向更新。

时间有重叠但不完全一致的记录会在本次同步中跳过，不建立双向映射，避免错误合并两个不同记录。

## 默认安全规则

- 默认只处理界面中选择的单日或连续 7 天。
- 建议先运行测试模式，再执行真实同步。
- 默认不会把 Google Calendar 导入到 aTimeLogger 的记录继续同步到 Toggl。
- 所有同步配置和映射仅保存在第二版本地文件中。

## 配置 Toggl

打开：

```text
run_atimelogger_sync_choose_date.pyw
```

Linux：

```bash
python3 run_atimelogger_sync_choose_date.py
```

进入 `Toggl 双向同步` 页面。

推荐填写 Toggl API token。API token 可以在 Toggl Track 个人资料设置中找到。

也可以不填写 token，改为填写 Toggl 账号和密码。

工作区 ID 可以留空，脚本会自动读取 Toggl 默认工作区。

## 活动类型配置

### Toggl → aTimeLogger

`Toggl → aTimeLogger 活动类型` 决定从 Toggl 导入的记录写入哪个 aTimeLogger 活动类型。

如果填写的是 aTimeLogger 分组，脚本会选择该分组下排序最前的可写活动。

### aTimeLogger → Toggl

`aTimeLogger → Toggl 类型筛选` 用于限制哪些 aTimeLogger 活动类型可以导出到 Toggl。

筛选内容必须与 aTimeLogger 中实际活动类型名称完全一致。留空表示允许导出所有非 Google Calendar、且尚未映射的记录。测试结果会分别显示可导出数量、已映射数量、Google Calendar 排除数量和类型筛选排除数量。

如果筛选中包含不存在、已归档或分组类型，测试和真实同步会直接报错，不再静默跳过全部记录。

多个类型使用英文逗号分隔：

```text
授课,备课,批改作业
```

留空表示所有类型均可导出，但 Google Calendar 导入记录仍默认排除。

## 操作流程

1. 打开 `Toggl 双向同步` 页面。
2. 填写 Toggl API token，或账号和密码。
3. 选择同步方向。
4. 设置 aTimeLogger 活动类型和筛选。
5. 选择日期或连续 7 天。
6. 点击 `保存配置`。
7. 点击 `测试模式`，检查预计创建和更新数量。
8. 确认无误后点击 `执行双向同步`。

`测试模式` 可以反复运行。它只读取和计算预计结果，不会创建、更新或覆盖 Toggl、aTimeLogger 记录，也不会更新双向同步映射状态。测试结果显示在固定的滚动区域中，不会遮挡测试按钮。

测试结果标题会明确显示 `测试完成（未写入）`。真实同步发生失败或冲突时，结果区域会显示失败动作、记录 ID 和接口返回原因，不会把失败显示为普通同步完成。

## 自动同步方向

在 `自动同步` 页面的 `自动同步内容` 中，可以独立勾选：

```text
Google Calendar → aTimeLogger
Toggl → aTimeLogger
aTimeLogger → Toggl
```

保存自动同步设置后，登录系统后同步、打开脚本时同步、固定时间同步和 `立即后台同步` 都只运行已勾选的内容。

两个 Toggl 方向可以只勾选一个，也可以同时勾选。两个方向同时勾选时，后台任务会执行双向同步。

自动同步方向与 `Toggl 双向同步` 页面中的手动同步方向互相独立。自动同步仍会使用该页面保存的账号、活动类型和筛选规则。

第二版使用独立的自动任务名称，Windows 计划任务、Windows 登录启动项和 Linux systemd 用户单元不会覆盖第一版任务。

Windows 保存固定时间同步时，会优先创建 Windows 计划任务。如果系统拒绝访问，程序会自动改用当前用户本地定时器，不需要管理员权限。该方式会在用户登录后运行，电脑关机、休眠或停留在登录界面时不会执行。

## 本地配置文件

| 文件 | 用途 |
| --- | --- |
| `.toggl-atimelogger-config.json` | Toggl 登录信息、工作区、方向和筛选配置 |
| `.toggl-atimelogger-state.json` | 双向记录映射和上次同步指纹 |

这两个文件已加入 `.gitignore`。

`.toggl-atimelogger-config.json` 可能包含 Toggl API token、账号或密码，必须安全保管。

不要删除 `.toggl-atimelogger-state.json`。删除后脚本会失去原有映射，虽然会尝试精确匹配，但仍可能产生重复记录。

## 命令行使用

测试今天的双向同步：

```bash
npm run sync:toggl-atimelogger -- --dry-run
```

同步指定日期：

```bash
npm run sync:toggl-atimelogger -- --date 2026-06-13
```

明确覆盖配置中的测试模式并真实写入：

```bash
npm run sync:toggl-atimelogger -- --date 2026-06-13 --write
```

图形界面的 `执行双向同步` 和自动同步任务会自动使用 `--write`，不会被残留的 `TOGGL_ATIMELOGGER_DRY_RUN=true` 误改为只读测试。

同步日期范围：

```bash
npm run sync:toggl-atimelogger -- --from 2026-06-09 --to 2026-06-15
```

指定方向：

```bash
npm run sync:toggl-atimelogger -- --date 2026-06-13 --direction toggl-to-atimelogger
```

方向可选值：

- `both`
- `toggl-to-atimelogger`
- `atimelogger-to-toggl`

## 当前限制

- 不同步正在计时的记录。
- 不自动传播删除操作。
- 冲突记录不会自动选择覆盖方向。
- Toggl 任务和计费属性暂不映射到 aTimeLogger。
- Toggl 项目和客户在 aTimeLogger 中以备注字段保留，因为 aTimeLogger 没有对应的原生字段。
- 从 Toggl 导入到 aTimeLogger 的记录统一使用配置的 aTimeLogger 活动类型。
- 从 aTimeLogger 导出到 Toggl 时，记录描述优先使用备注内容，没有备注时使用活动类型名称。
- 双向映射状态依赖本地 `.toggl-atimelogger-state.json` 文件。
- “仅手动/非集成记录”是基于 Toggl 来源字段的启发式判断；如果 Toggl 更改来源字段，需要更新关键词。

## 验证

第二版包含本地模拟 API 往返测试：

```bash
npm test
```

测试覆盖：

- 首次双向创建。
- Toggl 修改后更新 aTimeLogger。
- aTimeLogger 修改后更新 Toggl。
- 再次运行时不重复创建或更新。
