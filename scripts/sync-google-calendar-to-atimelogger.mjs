import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { execFileSync } from "node:child_process";
import { get as httpsGet } from "node:https";
import ical from "node-ical";
import { DateTime } from "luxon";

const DEFAULT_BASE_URL = "https://app.atimelogger.pro";
const DEFAULT_TIMEZONE = "Asia/Shanghai";
const DEFAULT_ACTIVITY_TYPE_NAME = "工作";
const EVENT_ID_MARKER = "Google Calendar Event ID:";
const STABLE_KEY_MARKER = "Stable Key:";
const CALENDAR_CONFIG_FILE = ".atimelogger-calendars.json";

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;

  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const equalsIndex = line.indexOf("=");
    if (equalsIndex === -1) continue;

    const key = line.slice(0, equalsIndex).trim();
    let value = line.slice(equalsIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function parseArgs(argv) {
  const args = {
    date: null,
    dryRun: false,
    calendarIds: null,
    days: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--date") {
      args.date = argv[index + 1];
      index += 1;
    } else if (arg.startsWith("--date=")) {
      args.date = arg.slice("--date=".length);
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else if (arg === "--days") {
      args.days = parseInt(argv[index + 1], 10);
      index += 1;
    } else if (arg.startsWith("--days=")) {
      args.days = parseInt(arg.slice("--days=".length), 10);
    } else if (arg === "--calendars") {
      args.calendarIds = String(argv[index + 1] || "").split(",").filter(Boolean);
      index += 1;
    } else if (arg.startsWith("--calendars=")) {
      args.calendarIds = arg.slice("--calendars=".length).split(",").filter(Boolean);
    }
  }

  return args;
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new ConfigError(`缺少配置 ${name}`);
  }
  return value;
}

class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = "ConfigError";
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const responseText = await response.text();

  if (!response.ok) {
    const body = responseText ? `；响应：${responseText.slice(0, 300)}` : "";
    throw new Error(`${options.method || "GET"} ${url} 失败：HTTP ${response.status}${body}`);
  }

  return responseText ? JSON.parse(responseText) : null;
}

async function getAtimeLoggerToken() {
  if (process.env.ATIMELOGGER_TOKEN) {
    return process.env.ATIMELOGGER_TOKEN;
  }

  if (process.env.ATIMELOGGER_CONFIG_JSON) {
    const config = JSON.parse(process.env.ATIMELOGGER_CONFIG_JSON);
    if (config?.token) return config.token;
  }

  if (process.env.ATIMELOGGER_USERNAME && process.env.ATIMELOGGER_PASSWORD) {
    const baseUrl = process.env.ATIMELOGGER_BASE_URL || DEFAULT_BASE_URL;
    const loginResult = await fetchJson(`${baseUrl}/auth/jwt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: process.env.ATIMELOGGER_USERNAME,
        password: process.env.ATIMELOGGER_PASSWORD,
      }),
    });

    if (loginResult?.token) return loginResult.token;
  }

  throw new ConfigError(
    "需要配置 aTimeLogger 登录令牌：请在 .dev.vars 中设置 ATIMELOGGER_TOKEN，或设置 ATIMELOGGER_USERNAME/ATIMELOGGER_PASSWORD"
  );
}

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

function isWritableActivityType(type) {
  return type && !type.group && !type.deleted && !type.archived;
}

function compareActivityTypes(left, right) {
  const leftOrder = Number.isFinite(left?.order) ? left.order : Number.MAX_SAFE_INTEGER;
  const rightOrder = Number.isFinite(right?.order) ? right.order : Number.MAX_SAFE_INTEGER;
  if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  return String(left?.name || "").localeCompare(String(right?.name || ""), "zh-Hans-CN");
}

function findActivityType(activityTypes, targetName) {
  const matches = activityTypes.filter(
    (type) => type?.name === targetName && !type.deleted && !type.archived
  );
  const writable = matches.find(isWritableActivityType);
  if (writable) {
    return { type: writable, requestedName: targetName, resolvedFromGroup: false };
  }

  const group = matches.find((type) => type.group);
  if (group) {
    const child = activityTypes
      .filter((type) => isWritableActivityType(type) && type.parentId === group.id)
      .sort(compareActivityTypes)[0];

    if (child) {
      return {
        type: child,
        requestedName: targetName,
        resolvedFromGroup: true,
        groupName: group.name,
      };
    }
  }

  return null;
}

function readCalendarConfig() {
  const configPath = path.resolve(process.cwd(), CALENDAR_CONFIG_FILE);
  if (!fs.existsSync(configPath)) {
    return { calendars: [], selectedCalendarIds: null };
  }

  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    return {
      calendars: Array.isArray(config?.calendars) ? config.calendars : [],
      selectedCalendarIds: Array.isArray(config?.selectedCalendarIds)
        ? config.selectedCalendarIds
        : null,
    };
  } catch (error) {
    throw new ConfigError(`${CALENDAR_CONFIG_FILE} 格式无效：${error.message}`);
  }
}

function getCalendarSources(requestedCalendarIds) {
  const config = readCalendarConfig();
  const sources = [];

  if (process.env.GOOGLE_CALENDAR_ICS_FILE) {
    sources.push({
      id: "default",
      name: "课程表",
      file: process.env.GOOGLE_CALENDAR_ICS_FILE,
    });
  } else if (process.env.GOOGLE_CALENDAR_ICS_URL) {
    sources.push({
      id: "default",
      name: "课程表",
      url: process.env.GOOGLE_CALENDAR_ICS_URL,
    });
  }

  for (const calendar of config.calendars) {
    if (!calendar?.id || !calendar?.name || !calendar?.url) continue;
    if (calendar.id === "default") continue;
    sources.push({
      id: String(calendar.id),
      name: String(calendar.name),
      url: String(calendar.url),
    });
  }

  const selectedIds = requestedCalendarIds ?? config.selectedCalendarIds;
  const selectedSources = selectedIds
    ? sources.filter((source) => selectedIds.includes(source.id))
    : sources;

  if (selectedSources.length === 0) {
    throw new ConfigError("没有选择可同步的 Google Calendar 日历");
  }

  return selectedSources;
}

async function loadCalendarData(source) {
  try {
    if (source.file) {
      return await ical.async.parseFile(source.file);
    }

    const icsText = await downloadText(source.url);
    return await ical.async.parseICS(icsText);
  } catch (error) {
    throw new Error(`读取日历“${source.name}”失败：${error.message}`);
  }
}

// node:https 下载兜底：ShellCrash 透明代理(fake-ip)下 undici fetch 可能超时，https 模块经同一路由稳定
function downloadTextViaHttps(url, redirectCount = 0) {
  return new Promise((resolve, reject) => {
    const request = httpsGet(url, { timeout: 60000 }, (response) => {
      if (
        response.statusCode >= 300 &&
        response.statusCode < 400 &&
        response.headers.location &&
        redirectCount < 5
      ) {
        response.resume();
        resolve(
          downloadTextViaHttps(
            new URL(response.headers.location, url).toString(),
            redirectCount + 1
          )
        );
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`HTTP ${response.statusCode}`));
        return;
      }
      let text = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        text += chunk;
      });
      response.on("end", () => resolve(text));
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error("请求超时(60s)")));
    request.on("error", reject);
  });
}

async function downloadText(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.text();
  } catch (error) {
    if (process.platform !== "win32") {
      // Linux/macOS：fetch 失败时降级到 node:https 下载
      return downloadTextViaHttps(url);
    }

    return execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        "$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; (Invoke-WebRequest -Uri $env:SYNC_DOWNLOAD_URL -UseBasicParsing -TimeoutSec 60).Content",
      ],
      {
        encoding: "utf8",
        env: { ...process.env, SYNC_DOWNLOAD_URL: url },
        maxBuffer: 25 * 1024 * 1024,
      }
    );
  }
}

function eventUid(instance) {
  return instance.uid || instance.id || instance.summary || "unknown-event";
}

// 旧格式事件 ID（含开始时间），保留向后兼容
function instanceId(instance, calendarId) {
  const uid = eventUid(instance);
  const start = instance.start instanceof Date ? instance.start.toISOString() : "unknown-start";
  return `${calendarId}:${uid}#${start}`;
}

// 稳定身份键：日历ID:uid:日期(按目标时区)，不含时分 —— 课程改时间仍是同一条
function stableKeyFor(calendarId, uid, dayISO) {
  return `${calendarId}:${uid}:${dayISO}`;
}

// 从已存在记录的评论里解析出稳定键：优先 Stable Key，其次从旧 Event ID 推导
function stableKeyFromComment(commentText, zoneName) {
  const stableMatch = commentText.match(/Stable Key:\s*([^\n]+)/);
  if (stableMatch?.[1]) return stableMatch[1].trim();

  const idMatch = commentText.match(/Google Calendar Event ID:\s*([^\n]+)/);
  if (idMatch?.[1]) {
    const raw = idMatch[1].trim();
    const hashIndex = raw.lastIndexOf("#");
    if (hashIndex === -1) return raw;
    const base = raw.slice(0, hashIndex); // calendarId:uid
    const startIso = raw.slice(hashIndex + 1);
    const day = DateTime.fromISO(startIso, { zone: "utc" }).setZone(zoneName);
    if (day.isValid) {
      return `${base}:${day.toISODate()}`;
    }
    return base;
  }
  return null;
}

function normalizeTitle(value) {
  return String(value || "Untitled").trim();
}

function buildComment(stableKey, eventId, summary, location, calendarName) {
  const lines = [
    `Google Calendar: ${summary}`,
    `Calendar: ${calendarName}`,
    `${STABLE_KEY_MARKER} ${stableKey}`,
    `${EVENT_ID_MARKER} ${eventId}`,
  ];

  if (location) {
    lines.splice(1, 0, `Location: ${location}`);
  }

  return lines.join("\n");
}

function getEventsForDay(calendarData, dayStart, dayEnd, calendar) {
  const from = dayStart.toJSDate();
  const to = dayEnd.toJSDate();
  const events = [];

  for (const item of Object.values(calendarData)) {
    if (item?.type !== "VEVENT") continue;
    if (item.status === "CANCELLED") continue;
    if (!item.start || !item.end) continue;

    const instances = item.rrule
      ? ical.expandRecurringEvent(item, {
          from,
          to,
          includeOverrides: true,
          excludeExdates: true,
          expandOngoing: true,
        })
      : [item];

    for (const instance of instances) {
      if (!instance.start || !instance.end) continue;
      if (instance.isFullDay || instance.start.dateOnly || instance.end.dateOnly) continue;

      const start = DateTime.fromJSDate(instance.start).setZone(dayStart.zoneName);
      const finish = DateTime.fromJSDate(instance.end).setZone(dayStart.zoneName);
      if (!start.isValid || !finish.isValid) continue;
      if (finish <= dayStart || start > dayEnd) continue;

      const dayISO = start.toISODate();
      const uid = eventUid(instance);

      events.push({
        id: instanceId(instance, calendar.id),
        stableKey: stableKeyFor(calendar.id, uid, dayISO),
        calendarId: calendar.id,
        calendarName: calendar.name,
        summary: normalizeTitle(instance.summary),
        location: String(instance.location || "").trim(),
        start,
        finish,
        startIso: instance.start.toISOString(),
        finishIso: instance.end.toISOString(),
      });
    }
  }

  events.sort((a, b) => a.start.toMillis() - b.start.toMillis());
  return events;
}

function flattenIntervals(daysIntervals) {
  if (!Array.isArray(daysIntervals)) return [];
  return daysIntervals.flatMap((day) => Array.isArray(day?.intervals) ? day.intervals : []);
}

async function getExistingIntervals(baseUrl, headers, date, zoneName) {
  const page = await fetchJson(`${baseUrl}/api/intervals?page=0&size=100`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      from: date,
      to: date,
      tags: [],
      groupBy: "day",
      timezone: zoneName,
    }),
  });

  return flattenIntervals(page?.content);
}

// 建立稳定键 -> 已存在记录 的索引（用于判断 新建/更新/跳过）
function buildExistingIndex(existingIntervals, typeId, zoneName) {
  const byStableKey = new Map();

  for (const interval of existingIntervals) {
    const comments = [interval.comment, interval.activityComment, interval.description].filter(Boolean);
    const commentText = comments.join("\n");
    if (!commentText.includes("Google Calendar")) continue;

    const key = stableKeyFromComment(commentText, zoneName);
    if (!key) continue;

    // 只接管我们自己同步出来的记录（有 interval id 和 activityId 才能更新）
    if (interval.id && interval.activityId && !byStableKey.has(key)) {
      byStableKey.set(key, interval);
    }
  }

  return byStableKey;
}

function sameTimeAndTitle(interval, event) {
  const existingStart = new Date(interval.start).getTime();
  const existingFinish = new Date(interval.finish).getTime();
  const wantStart = new Date(event.startIso).getTime();
  const wantFinish = new Date(event.finishIso).getTime();
  if (existingStart !== wantStart || existingFinish !== wantFinish) return false;

  const commentText = [interval.comment, interval.activityComment, interval.description]
    .filter(Boolean)
    .join("\n");
  const titleMatch = commentText.match(/Google Calendar:\s*([^\n]+)/);
  const existingTitle = normalizeTitle(titleMatch?.[1]).toLowerCase();
  return existingTitle === normalizeTitle(event.summary).toLowerCase();
}

async function createAtimeLoggerActivity(baseUrl, headers, typeId, event) {
  const comment = buildComment(event.stableKey, event.id, event.summary, event.location, event.calendarName);
  return fetchJson(`${baseUrl}/api/activities`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      status: "STOPPED",
      typeId,
      start: "",
      comment,
      tags: [],
      intervals: [
        {
          id: "",
          typeId,
          activityId: "",
          tags: [],
          start: event.startIso,
          finish: event.finishIso,
          comment,
        },
      ],
    }),
  });
}

// 变动更新：改写已存在记录的时间/标题（已验证机制，取自 sync-toggl-atimelogger）
async function updateAtimeLoggerActivity(baseUrl, headers, typeId, interval, event) {
  const comment = buildComment(event.stableKey, event.id, event.summary, event.location, event.calendarName);
  const intervalBody = {
    ...interval,
    typeId: typeId || interval.typeId,
    start: event.startIso,
    finish: event.finishIso,
    comment,
  };

  await fetchJson(
    `${baseUrl}/api/activities/${interval.activityId}/intervals/${interval.id}`,
    { method: "PUT", headers, body: JSON.stringify(intervalBody) }
  );

  const activity = await fetchJson(
    `${baseUrl}/api/activities/${interval.activityId}`,
    { headers }
  );
  const activityBody = {
    ...activity,
    typeId: typeId || activity.typeId,
    comment,
    intervals: (activity?.intervals || []).map((item) =>
      item.id === interval.id ? { ...item, ...intervalBody } : item
    ),
  };
  return fetchJson(`${baseUrl}/api/activities/${interval.activityId}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(activityBody),
  });
}

async function syncOneDay(ctx, targetDate) {
  const { baseUrl, headers, activityType, zoneName, calendarSources, dryRun, activityTypeName, activityTypeResolution } = ctx;
  const date = targetDate.toISODate();
  const dayStart = targetDate.startOf("day");
  const dayEnd = targetDate.endOf("day");

  const events = [];
  for (const calendar of calendarSources) {
    const calendarData = await loadCalendarData(calendar);
    events.push(...getEventsForDay(calendarData, dayStart, dayEnd, calendar));
  }
  events.sort((a, b) => a.start.toMillis() - b.start.toMillis());

  const summary = {
    date,
    timezone: zoneName,
    calendars: calendarSources.map((calendar) => calendar.name),
    calendarEvents: events.length,
    activityType: activityTypeName,
    resolvedActivityType: activityType?.name,
    resolvedFromGroup: Boolean(activityTypeResolution?.resolvedFromGroup),
    created: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    dryRun,
    failures: [],
  };

  if (dryRun && !activityType) {
    summary.skipped = events.length;
    summary.authConfigured = false;
    return summary;
  }

  const existingIntervals = await getExistingIntervals(baseUrl, headers, date, zoneName);
  const index = buildExistingIndex(existingIntervals, activityType.id, zoneName);

  for (const event of events) {
    const existing = index.get(event.stableKey);

    if (existing) {
      if (sameTimeAndTitle(existing, event)) {
        summary.skipped += 1;
        continue;
      }
      if (dryRun) {
        summary.updated += 1;
        continue;
      }
      try {
        await updateAtimeLoggerActivity(baseUrl, headers, activityType.id, existing, event);
        summary.updated += 1;
      } catch (error) {
        summary.failed += 1;
        summary.failures.push({
          calendar: event.calendarName,
          title: event.summary,
          start: event.start.toISO(),
          action: "update",
          reason: error.message,
        });
      }
      continue;
    }

    if (dryRun) {
      summary.created += 1;
      continue;
    }

    try {
      const created = await createAtimeLoggerActivity(baseUrl, headers, activityType.id, event);
      // 把新建结果并入索引，避免同一天同键重复
      if (created?.intervals?.[0]) {
        index.set(event.stableKey, { ...created.intervals[0], comment: buildComment(event.stableKey, event.id, event.summary, event.location, event.calendarName) });
      }
      summary.created += 1;
    } catch (error) {
      summary.failed += 1;
      summary.failures.push({
        calendar: event.calendarName,
        title: event.summary,
        start: event.start.toISO(),
        action: "create",
        reason: error.message,
      });
    }
  }

  return summary;
}

async function main() {
  loadEnvFile(path.resolve(process.cwd(), ".dev.vars"));
  loadEnvFile(path.resolve(process.cwd(), ".env"));

  const args = parseArgs(process.argv.slice(2));
  const zoneName = process.env.SYNC_TIMEZONE || DEFAULT_TIMEZONE;
  const activityTypeName = process.env.ATIMELOGGER_ACTIVITY_TYPE_NAME || DEFAULT_ACTIVITY_TYPE_NAME;
  const dryRun = args.dryRun || process.env.ATIMELOGGER_DRY_RUN === "true";
  const days = Math.max(1, args.days || parseInt(process.env.SYNC_DAYS || "1", 10) || 1);
  const targetDate = args.date && args.date !== "today"
    ? DateTime.fromISO(args.date, { zone: zoneName })
    : DateTime.now().setZone(zoneName);

  if (!targetDate.isValid) {
    throw new ConfigError(`日期无效：${args.date}`);
  }

  const calendarSources = getCalendarSources(args.calendarIds);

  let token;
  let activityType = null;
  let activityTypeResolution = null;
  let headers = null;
  const baseUrl = process.env.ATIMELOGGER_BASE_URL || DEFAULT_BASE_URL;

  try {
    token = await getAtimeLoggerToken();
    headers = authHeaders(token);
    const activityTypes = await fetchJson(`${baseUrl}/api/types`, { headers });
    activityTypeResolution = findActivityType(
      Array.isArray(activityTypes) ? activityTypes : [],
      activityTypeName
    );
    activityType = activityTypeResolution?.type || null;
    if (!activityType?.id) {
      throw new ConfigError(`aTimeLogger 中没有找到活动类型：${activityTypeName}`);
    }
  } catch (error) {
    if (dryRun && error instanceof ConfigError) {
      // 无凭据的 dry-run：仅解析日历
      const ctx = { baseUrl, headers, activityType: null, zoneName, calendarSources, dryRun, activityTypeName, activityTypeResolution };
      const results = [];
      for (let offset = 0; offset < days; offset += 1) {
        results.push(await syncOneDay(ctx, targetDate.plus({ days: offset })));
      }
      console.log(JSON.stringify(days === 1 ? results[0] : foldSummaries(results), null, 2));
      return;
    }
    throw error;
  }

  const ctx = { baseUrl, headers, activityType, zoneName, calendarSources, dryRun, activityTypeName, activityTypeResolution };
  const results = [];
  for (let offset = 0; offset < days; offset += 1) {
    results.push(await syncOneDay(ctx, targetDate.plus({ days: offset })));
  }

  const output = days === 1 ? results[0] : foldSummaries(results);
  console.log(JSON.stringify(output, null, 2));

  if (results.some((r) => r.failed > 0)) {
    process.exitCode = 1;
  }
}

function foldSummaries(results) {
  const totals = {
    dateFrom: results[0]?.date,
    dateTo: results[results.length - 1]?.date,
    days: results.length,
    timezone: results[0]?.timezone,
    calendars: results[0]?.calendars,
    activityType: results[0]?.activityType,
    calendarEvents: 0,
    created: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    dryRun: results[0]?.dryRun,
    perDay: [],
    failures: [],
  };
  for (const r of results) {
    totals.calendarEvents += r.calendarEvents || 0;
    totals.created += r.created || 0;
    totals.updated += r.updated || 0;
    totals.skipped += r.skipped || 0;
    totals.failed += r.failed || 0;
    totals.perDay.push({ date: r.date, created: r.created, updated: r.updated, skipped: r.skipped, failed: r.failed });
    if (Array.isArray(r.failures)) totals.failures.push(...r.failures);
  }
  return totals;
}

main().catch((error) => {
  const message = error instanceof ConfigError ? error.message : `同步失败：${error.message}`;
  console.error(message);
  process.exitCode = 1;
});
