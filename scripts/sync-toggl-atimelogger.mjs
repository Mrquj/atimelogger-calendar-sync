import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { DateTime } from "luxon";

const DEFAULT_ATIMELOGGER_BASE_URL = "https://app.atimelogger.pro";
const DEFAULT_TOGGL_BASE_URL = "https://api.track.toggl.com/api/v9";
const DEFAULT_TIMEZONE = "Asia/Shanghai";
const DEFAULT_ACTIVITY_TYPE_NAME = "工作";
const CONFIG_FILE = ".toggl-atimelogger-config.json";
const STATE_FILE = ".toggl-atimelogger-state.json";
const TOGGL_MARKER = "Toggl Time Entry ID:";
const TOGGL_PROJECT_ID_MARKER = "Toggl Project ID:";
const GOOGLE_CALENDAR_MARKER = "Google Calendar Event ID:";
const METADATA_VERSION = 2;
const OUTBOUND_TAG_VERSION = 1;
const DEFAULT_CALENDAR_SOURCE_KEYWORDS = ["calendar", "google calendar", "outlook", "ical"];

class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = "ConfigError";
  }
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const rawLine of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const equalsIndex = line.indexOf("=");
    if (equalsIndex < 0) continue;
    const key = line.slice(0, equalsIndex).trim();
    let value = line.slice(equalsIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

function readJsonFile(fileName, fallback) {
  const filePath = path.resolve(process.cwd(), fileName);
  if (!fs.existsSync(filePath)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    throw new ConfigError(`${fileName} 格式无效：${error.message}`);
  }
}

function writeJsonFile(fileName, value) {
  fs.writeFileSync(
    path.resolve(process.cwd(), fileName),
    `${JSON.stringify(value, null, 2)}\n`,
    "utf8"
  );
}

function parseArgs(argv) {
  const args = {
    date: null,
    from: null,
    to: null,
    direction: null,
    dryRun: false,
    forceWrite: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--date") {
      args.date = next;
      index += 1;
    } else if (arg.startsWith("--date=")) {
      args.date = arg.slice("--date=".length);
    } else if (arg === "--from") {
      args.from = next;
      index += 1;
    } else if (arg.startsWith("--from=")) {
      args.from = arg.slice("--from=".length);
    } else if (arg === "--to") {
      args.to = next;
      index += 1;
    } else if (arg.startsWith("--to=")) {
      args.to = arg.slice("--to=".length);
    } else if (arg === "--direction") {
      args.direction = next;
      index += 1;
    } else if (arg.startsWith("--direction=")) {
      args.direction = arg.slice("--direction=".length);
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else if (arg === "--write") {
      args.forceWrite = true;
    }
  }
  return args;
}

function configValue(config, envName, configName, fallback = null) {
  if (process.env[envName] !== undefined) return process.env[envName];
  if (config?.[configName] !== undefined && config?.[configName] !== null) {
    return config[configName];
  }
  return fallback;
}

function booleanValue(value, fallback = false) {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "boolean") return value;
  return String(value).toLowerCase() === "true";
}

function buildConfig(args) {
  const fileConfig = readJsonFile(CONFIG_FILE, {});
  const direction = args.direction || configValue(
    fileConfig,
    "TOGGL_ATIMELOGGER_DIRECTION",
    "direction",
    "both"
  );
  if (!["both", "toggl-to-atimelogger", "atimelogger-to-toggl"].includes(direction)) {
    throw new ConfigError(`同步方向无效：${direction}`);
  }

  return {
    direction,
    dryRun: args.forceWrite
      ? false
      : args.dryRun || booleanValue(
        configValue(fileConfig, "TOGGL_ATIMELOGGER_DRY_RUN", "dryRun", false)
      ),
    timezone: configValue(fileConfig, "SYNC_TIMEZONE", "timezone", DEFAULT_TIMEZONE),
    atimeBaseUrl: configValue(
      fileConfig,
      "ATIMELOGGER_BASE_URL",
      "atimeloggerBaseUrl",
      DEFAULT_ATIMELOGGER_BASE_URL
    ),
    atimeToken: configValue(fileConfig, "ATIMELOGGER_TOKEN", "atimeloggerToken"),
    atimeUsername: configValue(fileConfig, "ATIMELOGGER_USERNAME", "atimeloggerUsername"),
    atimePassword: configValue(fileConfig, "ATIMELOGGER_PASSWORD", "atimeloggerPassword"),
    atimeActivityTypeName: configValue(
      fileConfig,
      "TOGGL_ATIMELOGGER_ACTIVITY_TYPE_NAME",
      "atimeloggerActivityTypeName",
      configValue(fileConfig, "ATIMELOGGER_ACTIVITY_TYPE_NAME", "activityTypeName", DEFAULT_ACTIVITY_TYPE_NAME)
    ),
    atimeToTogglTypeNames: String(
      configValue(fileConfig, "ATIMELOGGER_TO_TOGGL_TYPE_NAMES", "atimeloggerToTogglTypeNames", "")
    )
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    includeGoogleCalendar: booleanValue(
      configValue(fileConfig, "TOGGL_INCLUDE_GOOGLE_CALENDAR", "includeGoogleCalendar", false)
    ),
    togglBaseUrl: configValue(fileConfig, "TOGGL_BASE_URL", "togglBaseUrl", DEFAULT_TOGGL_BASE_URL),
    togglApiToken: configValue(fileConfig, "TOGGL_API_TOKEN", "togglApiToken"),
    togglUsername: configValue(fileConfig, "TOGGL_USERNAME", "togglUsername"),
    togglPassword: configValue(fileConfig, "TOGGL_PASSWORD", "togglPassword"),
    togglWorkspaceId: configValue(fileConfig, "TOGGL_WORKSPACE_ID", "togglWorkspaceId"),
    togglSourceFilter: configValue(
      fileConfig,
      "TOGGL_SOURCE_FILTER",
      "togglSourceFilter",
      "exclude-calendar"
    ),
    calendarSourceKeywords: String(
      configValue(
        fileConfig,
        "TOGGL_CALENDAR_SOURCE_KEYWORDS",
        "calendarSourceKeywords",
        DEFAULT_CALENDAR_SOURCE_KEYWORDS.join(",")
      )
    )
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
    duplicatePolicy: configValue(
      fileConfig,
      "TOGGL_DUPLICATE_POLICY",
      "duplicatePolicy",
      "exact"
    ),
  };
}

function dateRange(args, timezone) {
  const today = DateTime.now().setZone(timezone);
  const fromText = args.date || args.from || today.toISODate();
  const toText = args.date || args.to || fromText;
  const from = DateTime.fromISO(fromText, { zone: timezone }).startOf("day");
  const to = DateTime.fromISO(toText, { zone: timezone }).endOf("day");
  if (!from.isValid || !to.isValid || to < from) {
    throw new ConfigError(`日期范围无效：${fromText} 至 ${toText}`);
  }
  return { from, to, fromDate: from.toISODate(), toDate: to.toISODate() };
}

function basicAuth(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`, "utf8").toString("base64")}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  if (!response.ok) {
    const body = text ? `；响应：${text.slice(0, 500)}` : "";
    throw new Error(`${options.method || "GET"} ${url} 失败：HTTP ${response.status}${body}`);
  }
  return text ? JSON.parse(text) : null;
}

async function getAtimeToken(config) {
  if (config.atimeToken) return config.atimeToken;
  if (!config.atimeUsername || !config.atimePassword) {
    throw new ConfigError("需要配置 aTimeLogger token，或账号和密码");
  }
  const login = await requestJson(`${config.atimeBaseUrl}/auth/jwt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: config.atimeUsername,
      password: config.atimePassword,
    }),
  });
  if (!login?.token) throw new ConfigError("aTimeLogger 登录成功但没有返回 token");
  return login.token;
}

function getTogglHeaders(config) {
  if (config.togglApiToken) {
    return {
      Authorization: basicAuth(config.togglApiToken, "api_token"),
      "Content-Type": "application/json",
    };
  }
  if (config.togglUsername && config.togglPassword) {
    return {
      Authorization: basicAuth(config.togglUsername, config.togglPassword),
      "Content-Type": "application/json",
    };
  }
  throw new ConfigError("需要配置 Toggl API token，或 Toggl 账号和密码");
}

async function resolveWorkspaceId(config, togglHeaders) {
  if (config.togglWorkspaceId) return Number(config.togglWorkspaceId);
  const me = await requestJson(`${config.togglBaseUrl}/me`, { headers: togglHeaders });
  const workspaceId = me?.default_workspace_id ?? me?.wid;
  if (!workspaceId) throw new ConfigError("无法自动获取 Toggl 默认工作区 ID");
  return Number(workspaceId);
}

function atimeHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

function isWritableActivityType(type) {
  return type && !type.group && !type.deleted && !type.archived;
}

function compareTypes(left, right) {
  const leftOrder = Number.isFinite(left?.order) ? left.order : Number.MAX_SAFE_INTEGER;
  const rightOrder = Number.isFinite(right?.order) ? right.order : Number.MAX_SAFE_INTEGER;
  return leftOrder - rightOrder || String(left?.name || "").localeCompare(String(right?.name || ""));
}

function resolveActivityType(types, name) {
  const matches = types.filter(
    (type) => type?.name === name && !type.deleted && !type.archived
  );
  const writable = matches.find(isWritableActivityType);
  if (writable) return writable;
  const group = matches.find((type) => type.group);
  if (!group) return null;
  return types
    .filter((type) => isWritableActivityType(type) && type.parentId === group.id)
    .sort(compareTypes)[0] || null;
}

async function fetchTogglEntries(config, headers, range) {
  const params = new URLSearchParams({
    start_date: range.from.toUTC().toISO(),
    end_date: range.to.toUTC().toISO(),
    meta: "true",
  });
  const entries = await requestJson(`${config.togglBaseUrl}/me/time_entries?${params}`, { headers });
  return (Array.isArray(entries) ? entries : []).filter(
    (entry) => entry?.id && entry?.start && entry?.stop && !entry?.server_deleted_at && !entry?.deleted_at
  );
}

function objectText(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(objectText).join(" ");
  if (typeof value === "object") return Object.values(value).map(objectText).join(" ");
  return "";
}

function togglSourceText(entry) {
  return [
    entry.created_with,
    entry.event_metadata?.origin_feature,
    entry.integration_ext_type,
    entry.integration_ext_id,
    entry.integration_provider,
  ]
    .map(objectText)
    .join(" ")
    .toLowerCase();
}

function hasIntegrationSource(entry) {
  return Boolean(
    entry.integration_ext_id
    || entry.integration_ext_type
    || entry.integration_provider
  );
}

function isCalendarSource(entry, config) {
  const sourceText = togglSourceText(entry);
  return config.calendarSourceKeywords.some((keyword) => sourceText.includes(keyword));
}

function togglEntryAllowed(entry, config) {
  if (config.togglSourceFilter === "all") return true;
  if (config.togglSourceFilter === "exclude-calendar") {
    return !isCalendarSource(entry, config);
  }
  if (config.togglSourceFilter === "manual-only") {
    return !isCalendarSource(entry, config) && !hasIntegrationSource(entry);
  }
  throw new ConfigError(`Toggl 来源过滤规则无效：${config.togglSourceFilter}`);
}

function flattenIntervals(days) {
  if (!Array.isArray(days)) return [];
  return days.flatMap((day) => Array.isArray(day?.intervals) ? day.intervals : []);
}

async function fetchAtimeIntervals(config, headers, range) {
  const all = [];
  let page = 0;
  while (page < 100) {
    const result = await requestJson(`${config.atimeBaseUrl}/api/intervals?page=${page}&size=100`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        from: range.fromDate,
        to: range.toDate,
        tags: [],
        groupBy: "day",
        timezone: config.timezone,
      }),
    });
    all.push(...flattenIntervals(result?.content));
    if (result?.last !== false) break;
    page += 1;
  }
  return all.filter((interval) => interval?.id && interval?.activityId && interval?.start && interval?.finish);
}

function normalizeText(value) {
  return String(value || "").trim();
}

function hash(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function togglFingerprint(entry) {
  return hash({
    description: normalizeText(entry.description),
    start: new Date(entry.start).toISOString(),
    stop: new Date(entry.stop).toISOString(),
    tags: [...(entry.tags || [])].sort(),
    billable: Boolean(entry.billable),
  });
}

function togglMetadataFingerprint(entry) {
  return hash({
    projectId: Number(entry.project_id ?? entry.pid) || null,
    projectName: normalizeText(entry.project_name),
    clientId: Number(entry.client_id) || null,
    clientName: normalizeText(entry.client_name),
    tags: [...(entry.tags || [])].map(normalizeText).filter(Boolean).sort(),
  });
}

function atimeFingerprint(interval) {
  return hash({
    typeId: interval.typeId,
    start: new Date(interval.start).toISOString(),
    finish: new Date(interval.finish).toISOString(),
    comment: normalizeText(interval.comment),
    tags: normalizedTags(interval.tags).sort(),
  });
}

function mappingKey(workspaceId, togglId) {
  return `${workspaceId}:${togglId}`;
}

function extractTogglMarker(comment) {
  const match = normalizeText(comment).match(/Toggl Time Entry ID:\s*(\d+):(\d+)/);
  if (!match) return null;
  return { workspaceId: Number(match[1]), togglId: Number(match[2]) };
}

function extractTogglProjectId(comment) {
  const match = normalizeText(comment).match(/Toggl Project ID:\s*(\d+)/);
  return match ? Number(match[1]) : null;
}

function normalizedTags(tags) {
  return [...new Set((tags || []).map(normalizeText).filter(Boolean))];
}

function togglComment(entry, workspaceId) {
  const description = normalizeText(entry.description) || `Toggl #${entry.id}`;
  const lines = [`Toggl: ${description}`];
  const projectId = Number(entry.project_id ?? entry.pid) || null;
  const projectName = normalizeText(entry.project_name);
  const clientName = normalizeText(entry.client_name);
  const tags = normalizedTags(entry.tags);
  if (projectName) lines.push(`Toggl Project: ${projectName}`);
  if (projectId) lines.push(`${TOGGL_PROJECT_ID_MARKER} ${projectId}`);
  if (clientName) lines.push(`Toggl Client: ${clientName}`);
  if (tags.length > 0) lines.push(`Toggl Tags: ${tags.join(", ")}`);
  lines.push(`${TOGGL_MARKER} ${workspaceId}:${entry.id}`);
  return lines.join("\n");
}

function descriptionFromAtime(interval, typeName) {
  const comment = normalizeText(interval.comment);
  const togglLine = comment.match(/^Toggl:\s*(.+)$/m)?.[1]?.trim();
  if (togglLine) return togglLine;
  const calendarLine = comment.match(/^Google Calendar:\s*(.+)$/m)?.[1]?.trim();
  if (calendarLine) return calendarLine;
  const firstUsefulLine = comment
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith(TOGGL_MARKER) && !line.startsWith(GOOGLE_CALENDAR_MARKER));
  return firstUsefulLine || typeName || "aTimeLogger";
}

function sameDescription(entry, interval, typeName) {
  return normalizeText(entry.description).toLowerCase()
    === descriptionFromAtime(interval, typeName).toLowerCase();
}

function exactTimeMatch(entry, interval) {
  return new Date(interval.start).getTime() === new Date(entry.start).getTime()
    && new Date(interval.finish).getTime() === new Date(entry.stop).getTime();
}

function timesOverlap(entry, interval) {
  const entryStart = new Date(entry.start).getTime();
  const entryStop = new Date(entry.stop).getTime();
  const intervalStart = new Date(interval.start).getTime();
  const intervalFinish = new Date(interval.finish).getTime();
  return entryStart < intervalFinish && intervalStart < entryStop;
}

function duplicateAtimeInterval(entry, intervals, mappedAtimeIds, typeById, policy) {
  if (policy === "none") return null;
  return intervals.find((interval) => {
    if (mappedAtimeIds.has(interval.id)) return false;
    const typeName = typeById.get(interval.typeId)?.name || "aTimeLogger";
    if (!sameDescription(entry, interval, typeName)) return false;
    if (policy === "exact") return exactTimeMatch(entry, interval);
    if (policy === "title-overlap") return timesOverlap(entry, interval);
    throw new ConfigError(`重复检查规则无效：${policy}`);
  }) || null;
}

function atimeExportSkipReason(interval, typeName, config) {
  if (!config.includeGoogleCalendar && normalizeText(interval.comment).includes(GOOGLE_CALENDAR_MARKER)) {
    return "google-calendar";
  }
  if (config.atimeToTogglTypeNames.length > 0 && !config.atimeToTogglTypeNames.includes(typeName)) {
    return "type-filter";
  }
  return null;
}

async function createAtimeFromToggl(config, headers, targetType, entry, workspaceId) {
  const comment = togglComment(entry, workspaceId);
  const tags = normalizedTags(entry.tags);
  return requestJson(`${config.atimeBaseUrl}/api/activities`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      status: "STOPPED",
      typeId: targetType.id,
      start: "",
      comment,
      tags,
      intervals: [{
        id: "",
        typeId: targetType.id,
        activityId: "",
        tags,
        start: new Date(entry.start).toISOString(),
        finish: new Date(entry.stop).toISOString(),
        comment,
      }],
    }),
  });
}

async function updateAtimeFromToggl(config, headers, interval, entry, workspaceId, targetTypeId) {
  const comment = togglComment(entry, workspaceId);
  const tags = normalizedTags(entry.tags);
  const intervalBody = {
    ...interval,
    typeId: targetTypeId || interval.typeId,
    start: new Date(entry.start).toISOString(),
    finish: new Date(entry.stop).toISOString(),
    comment,
    tags,
  };
  await requestJson(
    `${config.atimeBaseUrl}/api/activities/${interval.activityId}/intervals/${interval.id}`,
    { method: "PUT", headers, body: JSON.stringify(intervalBody) }
  );
  const activity = await requestJson(
    `${config.atimeBaseUrl}/api/activities/${interval.activityId}`,
    { headers }
  );
  const activityBody = {
    ...activity,
    typeId: targetTypeId || activity.typeId,
    comment,
    tags,
    intervals: (activity?.intervals || []).map((item) => (
      item.id === interval.id ? { ...item, ...intervalBody } : item
    )),
  };
  return requestJson(`${config.atimeBaseUrl}/api/activities/${interval.activityId}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(activityBody),
  });
}

function togglPayload(interval, typeName, workspaceId) {
  const start = new Date(interval.start);
  const finish = new Date(interval.finish);
  const projectId = extractTogglProjectId(interval.comment);
  const payload = {
    created_with: "atimelogger-sync-v2",
    description: descriptionFromAtime(interval, typeName),
    workspace_id: Number(workspaceId),
    start: start.toISOString(),
    stop: finish.toISOString(),
    tags: normalizedTags(interval.tags),
    tag_action: "replace",
  };
  if (projectId) payload.project_id = projectId;
  return payload;
}

async function createTogglFromAtime(config, headers, workspaceId, interval, typeName) {
  return requestJson(`${config.togglBaseUrl}/workspaces/${workspaceId}/time_entries`, {
    method: "POST",
    headers,
    body: JSON.stringify(togglPayload(interval, typeName, workspaceId)),
  });
}

async function updateTogglFromAtime(config, headers, workspaceId, togglId, interval, typeName) {
  return requestJson(`${config.togglBaseUrl}/workspaces/${workspaceId}/time_entries/${togglId}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(togglPayload(interval, typeName, workspaceId)),
  });
}

function newState() {
  return { version: 1, mappings: {} };
}

function directionAllows(direction, operation) {
  return direction === "both" || direction === operation;
}

function mappingFromPair(workspaceId, entry, interval) {
  return {
    togglId: Number(entry.id),
    workspaceId: Number(workspaceId),
    atimeActivityId: interval.activityId,
    atimeIntervalId: interval.id,
    atimeTypeId: interval.typeId,
    lastTogglFingerprint: togglFingerprint(entry),
    lastTogglMetadataFingerprint: togglMetadataFingerprint(entry),
    lastAtimeFingerprint: atimeFingerprint(interval),
    metadataVersion: METADATA_VERSION,
    outboundTagVersion: OUTBOUND_TAG_VERSION,
    lastSyncedAt: new Date().toISOString(),
  };
}

function updateMappingFingerprints(mapping, entry, interval) {
  mapping.lastTogglFingerprint = togglFingerprint(entry);
  mapping.lastTogglMetadataFingerprint = togglMetadataFingerprint(entry);
  mapping.lastAtimeFingerprint = atimeFingerprint(interval);
  mapping.metadataVersion = METADATA_VERSION;
  mapping.outboundTagVersion = OUTBOUND_TAG_VERSION;
  mapping.atimeActivityId = interval.activityId;
  mapping.atimeIntervalId = interval.id;
  mapping.atimeTypeId = interval.typeId;
  mapping.lastSyncedAt = new Date().toISOString();
}

function summaryTemplate(config, range, workspaceId, togglEntries, atimeIntervals) {
  return {
    from: range.fromDate,
    to: range.toDate,
    timezone: config.timezone,
    direction: config.direction,
    workspaceId,
    togglEntries: togglEntries.length,
    togglFilteredOut: 0,
    atimeIntervals: atimeIntervals.length,
    atimeAlreadyMapped: 0,
    atimeExcludedGoogleCalendar: 0,
    atimeExcludedByType: 0,
    atimeEligibleForToggl: 0,
    createdInAtimeLogger: 0,
    updatedInAtimeLogger: 0,
    movedToAtimeLoggerType: 0,
    createdInToggl: 0,
    updatedInToggl: 0,
    skipped: 0,
    duplicateSkipped: 0,
    conflicts: 0,
    failed: 0,
    dryRun: config.dryRun,
    details: [],
  };
}

async function main() {
  loadEnvFile(path.resolve(process.cwd(), ".dev.vars"));
  loadEnvFile(path.resolve(process.cwd(), ".env"));
  const args = parseArgs(process.argv.slice(2));
  const config = buildConfig(args);
  const range = dateRange(args, config.timezone);

  const atimeToken = await getAtimeToken(config);
  const atimeRequestHeaders = atimeHeaders(atimeToken);
  const togglRequestHeaders = getTogglHeaders(config);
  const workspaceId = await resolveWorkspaceId(config, togglRequestHeaders);

  const [types, allTogglEntries, atimeIntervals] = await Promise.all([
    requestJson(`${config.atimeBaseUrl}/api/types`, { headers: atimeRequestHeaders }),
    fetchTogglEntries(config, togglRequestHeaders, range),
    fetchAtimeIntervals(config, atimeRequestHeaders, range),
  ]);
  const togglEntries = allTogglEntries.filter((entry) => togglEntryAllowed(entry, config));
  const activityTypes = Array.isArray(types) ? types : [];
  const typeById = new Map(activityTypes.map((type) => [type.id, type]));
  if (directionAllows(config.direction, "atimelogger-to-toggl")) {
    const writableTypeNames = new Set(
      activityTypes.filter(isWritableActivityType).map((type) => type.name)
    );
    const invalidTypeNames = config.atimeToTogglTypeNames.filter(
      (name) => !writableTypeNames.has(name)
    );
    if (invalidTypeNames.length > 0) {
      throw new ConfigError(
        `aTimeLogger → Toggl 类型筛选不存在或不可写：${invalidTypeNames.join(", ")}。`
        + "请填写实际活动类型名称，或留空表示允许所有类型。"
      );
    }
  }
  const targetType = resolveActivityType(activityTypes, config.atimeActivityTypeName);
  if (!targetType?.id && directionAllows(config.direction, "toggl-to-atimelogger")) {
    throw new ConfigError(`aTimeLogger 中没有找到可写活动类型：${config.atimeActivityTypeName}`);
  }

  const state = readJsonFile(STATE_FILE, newState());
  if (!state.mappings || typeof state.mappings !== "object") state.mappings = {};
  const summary = summaryTemplate(config, range, workspaceId, togglEntries, atimeIntervals);
  summary.togglFilteredOut = allTogglEntries.length - togglEntries.length;
  const togglById = new Map(togglEntries.map((entry) => [Number(entry.id), entry]));
  const atimeById = new Map(atimeIntervals.map((interval) => [interval.id, interval]));
  const workspaceMappings = Object.values(state.mappings).filter(
    (mapping) => Number(mapping.workspaceId) === workspaceId
  );
  const mappedTogglIds = new Set(workspaceMappings.map((mapping) => Number(mapping.togglId)));
  const mappedAtimeIds = new Set(workspaceMappings.map((mapping) => mapping.atimeIntervalId));

  for (const interval of atimeIntervals) {
    const marker = extractTogglMarker(interval.comment);
    if (!marker || marker.workspaceId !== workspaceId) continue;
    const entry = togglById.get(marker.togglId);
    if (!entry) continue;
    const key = mappingKey(workspaceId, entry.id);
    if (!state.mappings[key]) {
      state.mappings[key] = mappingFromPair(workspaceId, entry, interval);
      mappedTogglIds.add(Number(entry.id));
      mappedAtimeIds.add(interval.id);
    }
  }

  for (const entry of togglEntries) {
    if (mappedTogglIds.has(Number(entry.id))) continue;
    const matchingInterval = duplicateAtimeInterval(
      entry,
      atimeIntervals,
      mappedAtimeIds,
      typeById,
      config.duplicatePolicy
    );
    if (!matchingInterval) continue;
    if (exactTimeMatch(entry, matchingInterval)) {
      const key = mappingKey(workspaceId, entry.id);
      state.mappings[key] = mappingFromPair(workspaceId, entry, matchingInterval);
      mappedTogglIds.add(Number(entry.id));
      mappedAtimeIds.add(matchingInterval.id);
      summary.details.push({
        action: "linked-existing-exact-match",
        togglId: entry.id,
        atimeIntervalId: matchingInterval.id,
      });
    } else {
      mappedTogglIds.add(Number(entry.id));
      mappedAtimeIds.add(matchingInterval.id);
      summary.duplicateSkipped += 1;
      summary.details.push({
        action: "duplicate-title-overlap-skipped",
        togglId: entry.id,
        atimeIntervalId: matchingInterval.id,
      });
    }
  }

  for (const [key, mapping] of Object.entries(state.mappings)) {
    if (Number(mapping.workspaceId) !== workspaceId) continue;
    const entry = togglById.get(Number(mapping.togglId));
    const interval = atimeById.get(mapping.atimeIntervalId);
    if (!entry || !interval) continue;
    const currentTogglFingerprint = togglFingerprint(entry);
    const currentTogglMetadataFingerprint = togglMetadataFingerprint(entry);
    const currentAtimeFingerprint = atimeFingerprint(interval);
    const marker = extractTogglMarker(interval.comment);
    const targetTypeChanged = Boolean(
      marker
      && targetType?.id
      && interval.typeId !== targetType.id
    );
    let togglChanged = Boolean(
      mapping.lastTogglFingerprint && mapping.lastTogglFingerprint !== currentTogglFingerprint
    );
    if (mapping.lastTogglMetadataFingerprint) {
      togglChanged ||= mapping.lastTogglMetadataFingerprint !== currentTogglMetadataFingerprint;
    } else if (marker) {
      // Existing Toggl-originated records need one metadata backfill after this feature is introduced.
      togglChanged = true;
    } else {
      mapping.lastTogglMetadataFingerprint = currentTogglMetadataFingerprint;
    }
    if (Number(mapping.metadataVersion || 0) < METADATA_VERSION) {
      if (marker) {
        togglChanged = true;
      } else {
        mapping.metadataVersion = METADATA_VERSION;
      }
    }
    if (targetTypeChanged) togglChanged = true;
    let atimeChanged = Boolean(
      mapping.lastAtimeFingerprint && mapping.lastAtimeFingerprint !== currentAtimeFingerprint
    );
    if (Number(mapping.outboundTagVersion || 0) < OUTBOUND_TAG_VERSION) {
      if (!marker && normalizedTags(interval.tags).length > 0) {
        atimeChanged = true;
      } else {
        mapping.outboundTagVersion = OUTBOUND_TAG_VERSION;
      }
    }

    if (togglChanged && atimeChanged) {
      summary.conflicts += 1;
      summary.details.push({ action: "conflict", togglId: entry.id, atimeIntervalId: interval.id });
      continue;
    }

    if (togglChanged && directionAllows(config.direction, "toggl-to-atimelogger")) {
      try {
        if (!config.dryRun) {
          await updateAtimeFromToggl(
            config,
            atimeRequestHeaders,
            interval,
            entry,
            workspaceId,
            targetType?.id
          );
          const updatedInterval = {
            ...interval,
            typeId: targetType?.id || interval.typeId,
            start: entry.start,
            finish: entry.stop,
            comment: togglComment(entry, workspaceId),
            tags: normalizedTags(entry.tags),
          };
          updateMappingFingerprints(mapping, entry, updatedInterval);
        }
        summary.updatedInAtimeLogger += 1;
        if (targetTypeChanged) summary.movedToAtimeLoggerType += 1;
      } catch (error) {
        summary.failed += 1;
        summary.details.push({
          action: "update-atimelogger-failed",
          togglId: entry.id,
          atimeIntervalId: interval.id,
          reason: error.message,
        });
      }
      continue;
    }

    if (atimeChanged && directionAllows(config.direction, "atimelogger-to-toggl")) {
      const typeName = typeById.get(interval.typeId)?.name || "aTimeLogger";
      try {
        if (!config.dryRun) {
          const updated = await updateTogglFromAtime(
            config,
            togglRequestHeaders,
            workspaceId,
            entry.id,
            interval,
            typeName
          );
          updateMappingFingerprints(
            mapping,
            { ...entry, ...(updated || togglPayload(interval, typeName, workspaceId)) },
            interval
          );
        }
        summary.updatedInToggl += 1;
      } catch (error) {
        summary.failed += 1;
        summary.details.push({
          action: "update-toggl-failed",
          togglId: entry.id,
          atimeIntervalId: interval.id,
          reason: error.message,
        });
      }
      continue;
    }

    summary.skipped += 1;
    if (!mapping.lastTogglFingerprint || !mapping.lastAtimeFingerprint) {
      updateMappingFingerprints(mapping, entry, interval);
    }
    state.mappings[key] = mapping;
  }

  if (directionAllows(config.direction, "atimelogger-to-toggl")) {
    for (const interval of atimeIntervals) {
      if (mappedAtimeIds.has(interval.id)) {
        summary.atimeAlreadyMapped += 1;
        continue;
      }
      const typeName = typeById.get(interval.typeId)?.name || "aTimeLogger";
      const reason = atimeExportSkipReason(interval, typeName, config);
      if (reason === "google-calendar") {
        summary.atimeExcludedGoogleCalendar += 1;
      } else if (reason === "type-filter") {
        summary.atimeExcludedByType += 1;
      } else {
        summary.atimeEligibleForToggl += 1;
      }
    }
  }

  if (directionAllows(config.direction, "toggl-to-atimelogger")) {
    for (const entry of togglEntries) {
      if (mappedTogglIds.has(Number(entry.id))) continue;
      try {
        if (!config.dryRun) {
          const created = await createAtimeFromToggl(
            config,
            atimeRequestHeaders,
            targetType,
            entry,
            workspaceId
          );
          const interval = created?.intervals?.[0];
          if (!created?.id || !interval?.id) {
            throw new Error("aTimeLogger 创建成功但响应中缺少活动或区间 ID");
          }
          state.mappings[mappingKey(workspaceId, entry.id)] = mappingFromPair(
            workspaceId,
            entry,
            interval
          );
          mappedAtimeIds.add(interval.id);
        }
        summary.createdInAtimeLogger += 1;
      } catch (error) {
        summary.failed += 1;
        summary.details.push({ action: "create-atimelogger-failed", togglId: entry.id, reason: error.message });
      }
    }
  }

  if (directionAllows(config.direction, "atimelogger-to-toggl")) {
    for (const interval of atimeIntervals) {
      if (mappedAtimeIds.has(interval.id)) continue;
      const typeName = typeById.get(interval.typeId)?.name || "aTimeLogger";
      if (atimeExportSkipReason(interval, typeName, config)) {
        summary.skipped += 1;
        continue;
      }
      try {
        if (!config.dryRun) {
          const created = await createTogglFromAtime(
            config,
            togglRequestHeaders,
            workspaceId,
            interval,
            typeName
          );
          if (!created?.id) throw new Error("Toggl 创建成功但响应中缺少时间记录 ID");
          state.mappings[mappingKey(workspaceId, created.id)] = mappingFromPair(
            workspaceId,
            created,
            interval
          );
        }
        summary.createdInToggl += 1;
      } catch (error) {
        summary.failed += 1;
        summary.details.push({
          action: "create-toggl-failed",
          atimeIntervalId: interval.id,
          reason: error.message,
        });
      }
    }
  }

  if (!config.dryRun) writeJsonFile(STATE_FILE, state);
  console.log(JSON.stringify(summary, null, 2));
  if (summary.failed > 0 || summary.conflicts > 0) process.exitCode = 1;
}

main().catch((error) => {
  const prefix = error instanceof ConfigError ? "" : "双向同步失败：";
  console.error(`${prefix}${error.message}`);
  process.exitCode = 1;
});
