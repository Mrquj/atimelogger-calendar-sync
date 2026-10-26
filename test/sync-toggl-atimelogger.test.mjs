import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

const PROJECT_DIR = path.resolve(import.meta.dirname, "..");
const SCRIPT = path.join(PROJECT_DIR, "scripts", "sync-toggl-atimelogger.mjs");

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function readBody(request) {
  return new Promise((resolve) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
    });
    request.on("end", () => resolve(body ? JSON.parse(body) : null));
  });
}

function json(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

function runSync(cwd, expectSuccess = true, dryRun = false) {
  return new Promise((resolve, reject) => {
    const args = [SCRIPT, "--date", "2026-06-13"];
    args.push(dryRun ? "--dry-run" : "--write");
    const child = spawn(
      process.execPath,
      args,
      {
        cwd,
        env: {
          ...process.env,
          NO_COLOR: "1",
          TOGGL_ATIMELOGGER_DRY_RUN: "true",
        },
      }
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0 && expectSuccess) {
        reject(new Error(`sync exited ${code}\n${stdout}\n${stderr}`));
        return;
      }
      resolve({
        code,
        summary: stdout.trim() ? JSON.parse(stdout) : null,
        stdout,
        stderr,
      });
    });
  });
}

test("creates, updates, then stabilizes bidirectional mappings", async (context) => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "toggl-atimelogger-test-"));
  context.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));

  const store = {
    toggl: [{
      id: 101,
      workspace_id: 123,
      description: "Toggl only",
      start: "2026-06-13T00:00:00.000Z",
      stop: "2026-06-13T01:00:00.000Z",
      project_id: 701,
      project_name: "Client Project",
      client_id: 801,
      client_name: "Acme",
      tags: ["toggl-tag"],
      billable: false,
    }, {
      id: 103,
      workspace_id: 123,
      description: "Exact duplicate",
      start: "2026-06-13T04:00:00.000Z",
      stop: "2026-06-13T05:00:00.000Z",
      tags: [],
      billable: false,
    }, {
      id: 104,
      workspace_id: 123,
      description: "Overlap duplicate",
      start: "2026-06-13T06:00:00.000Z",
      stop: "2026-06-13T07:00:00.000Z",
      tags: [],
      billable: false,
    }, {
      id: 999,
      workspace_id: 123,
      description: "Calendar quick add",
      start: "2026-06-13T08:00:00.000Z",
      stop: "2026-06-13T09:00:00.000Z",
      created_with: "calendar",
      event_metadata: { origin_feature: "calendar-view" },
      tags: [],
      billable: false,
    }, {
      id: 998,
      workspace_id: 123,
      description: "External integration",
      start: "2026-06-13T10:00:00.000Z",
      stop: "2026-06-13T11:00:00.000Z",
      integration_ext_id: "external-998",
      integration_ext_type: "task",
      integration_provider: { name: "external-system" },
      tags: [],
      billable: false,
    }],
    atime: [{
      id: "interval-201",
      activityId: "activity-201",
      typeId: "type-work",
      start: "2026-06-13T02:00:00.000Z",
      finish: "2026-06-13T03:00:00.000Z",
      tags: ["atime-tag"],
      comment: "aTime only",
    }, {
      id: "interval-301",
      activityId: "activity-301",
      typeId: "type-work",
      start: "2026-06-13T04:00:00.000Z",
      finish: "2026-06-13T05:00:00.000Z",
      tags: [],
      comment: "Exact duplicate",
    }, {
      id: "interval-401",
      activityId: "activity-401",
      typeId: "type-work",
      start: "2026-06-13T06:30:00.000Z",
      finish: "2026-06-13T07:30:00.000Z",
      tags: [],
      comment: "Overlap duplicate",
    }],
    types: [{
      id: "type-work",
      name: "工作",
      group: false,
      deleted: false,
      archived: false,
      order: 1,
    }],
    nextTogglId: 1000,
    nextAtimeId: 500,
  };

  const togglServer = http.createServer(async (request, response) => {
    if (request.method === "GET" && request.url === "/api/v9/me") {
      json(response, 200, { default_workspace_id: 123 });
      return;
    }
    if (request.method === "GET" && request.url.startsWith("/api/v9/me/time_entries")) {
      json(response, 200, store.toggl);
      return;
    }
    if (request.method === "POST" && request.url === "/api/v9/workspaces/123/time_entries") {
      const body = await readBody(request);
      if (body.workspace_id !== 123 || body.created_with !== "atimelogger-sync-v2") {
        json(response, 400, { error: "workspace_id and created_with are required" });
        return;
      }
      if (body.duration !== undefined) {
        json(response, 400, { error: "do not send duration together with stop" });
        return;
      }
      const entry = {
        ...body,
        id: store.nextTogglId++,
        workspace_id: 123,
        billable: false,
      };
      store.toggl.push(entry);
      json(response, 200, entry);
      return;
    }
    const updateMatch = request.url.match(/^\/api\/v9\/workspaces\/123\/time_entries\/(\d+)$/);
    if (request.method === "PUT" && updateMatch) {
      const body = await readBody(request);
      if (body.workspace_id !== 123 || body.created_with !== "atimelogger-sync-v2") {
        json(response, 400, { error: "workspace_id and created_with are required" });
        return;
      }
      const entry = store.toggl.find((item) => item.id === Number(updateMatch[1]));
      Object.assign(entry, body);
      json(response, 200, entry);
      return;
    }
    json(response, 404, { error: request.url });
  });

  const atimeServer = http.createServer(async (request, response) => {
    if (request.method === "POST" && request.url === "/auth/jwt") {
      json(response, 200, { token: "test-token" });
      return;
    }
    if (request.method === "GET" && request.url === "/api/types") {
      json(response, 200, store.types);
      return;
    }
    if (request.method === "POST" && request.url.startsWith("/api/intervals")) {
      json(response, 200, {
        content: [{ intervals: store.atime }],
        last: true,
      });
      return;
    }
    const activityMatch = request.url.match(/^\/api\/activities\/([^/]+)$/);
    if (request.method === "GET" && activityMatch) {
      const intervals = store.atime.filter((item) => item.activityId === activityMatch[1]);
      const first = intervals[0];
      json(response, 200, {
        id: activityMatch[1],
        status: "STOPPED",
        typeId: first?.typeId,
        start: null,
        comment: first?.comment || "",
        tags: first?.tags || [],
        intervals,
      });
      return;
    }
    if (request.method === "PUT" && activityMatch) {
      const body = await readBody(request);
      for (const update of body.intervals || []) {
        const interval = store.atime.find((item) => item.id === update.id);
        if (interval) Object.assign(interval, update, {
          comment: body.comment,
          tags: body.tags,
        });
      }
      json(response, 200, body);
      return;
    }
    if (request.method === "POST" && request.url === "/api/activities") {
      const body = await readBody(request);
      const activityId = `activity-${store.nextAtimeId}`;
      const interval = {
        ...body.intervals[0],
        id: `interval-${store.nextAtimeId++}`,
        activityId,
      };
      store.atime.push(interval);
      json(response, 200, { ...body, id: activityId, intervals: [interval] });
      return;
    }
    const updateMatch = request.url.match(
      /^\/api\/activities\/([^/]+)\/intervals\/([^/]+)$/
    );
    if (request.method === "PUT" && updateMatch) {
      const body = await readBody(request);
      const interval = store.atime.find((item) => item.id === updateMatch[2]);
      Object.assign(interval, body);
      json(response, 200, interval);
      return;
    }
    json(response, 404, { error: request.url });
  });

  const togglPort = await listen(togglServer);
  const atimePort = await listen(atimeServer);
  context.after(() => togglServer.close());
  context.after(() => atimeServer.close());

  fs.writeFileSync(
    path.join(tempDir, ".toggl-atimelogger-config.json"),
    JSON.stringify({
      direction: "both",
      togglApiToken: "test-api-token",
      togglBaseUrl: `http://127.0.0.1:${togglPort}/api/v9`,
      atimeloggerBaseUrl: `http://127.0.0.1:${atimePort}`,
      atimeloggerUsername: "test",
      atimeloggerPassword: "test",
      atimeloggerActivityTypeName: "工作",
      togglSourceFilter: "manual-only",
      calendarSourceKeywords: "calendar,google calendar,outlook,ical",
      duplicatePolicy: "title-overlap",
    })
  );

  const dryRun = (await runSync(tempDir, true, true)).summary;
  assert.equal(dryRun.dryRun, true);
  assert.equal(dryRun.createdInAtimeLogger, 1);
  assert.equal(dryRun.createdInToggl, 1);
  assert.equal(store.toggl.length, 5);
  assert.equal(store.atime.length, 3);
  assert.equal(fs.existsSync(path.join(tempDir, ".toggl-atimelogger-state.json")), false);

  const first = (await runSync(tempDir)).summary;
  assert.equal(first.createdInAtimeLogger, 1);
  assert.equal(first.createdInToggl, 1);
  assert.equal(first.togglFilteredOut, 2);
  assert.equal(first.duplicateSkipped, 1);
  assert.equal(first.failed, 0);
  assert.equal(store.toggl.length, 6);
  assert.equal(store.atime.length, 4);
  assert.equal(store.atime.some((interval) => /Calendar quick add/.test(interval.comment)), false);
  assert.equal(store.atime.some((interval) => /External integration/.test(interval.comment)), false);
  const imported = store.atime.find((interval) => /Toggl Time Entry ID: 123:101/.test(interval.comment));
  assert.match(imported.comment, /Toggl Project: Client Project/);
  assert.match(imported.comment, /Toggl Project ID: 701/);
  assert.match(imported.comment, /Toggl Client: Acme/);
  assert.match(imported.comment, /Toggl Tags: toggl-tag/);
  assert.deepEqual(imported.tags, ["toggl-tag"]);
  assert.deepEqual(
    store.toggl.find((entry) => entry.description === "aTime only").tags,
    ["atime-tag"]
  );

  store.toggl.find((entry) => entry.id === 101).description = "Toggl changed";
  store.toggl.find((entry) => entry.id === 101).project_name = "Changed Project";
  store.toggl.find((entry) => entry.id === 101).client_name = "Changed Client";
  store.toggl.find((entry) => entry.id === 101).tags = ["changed-tag"];
  store.atime.find((interval) => interval.id === "interval-201").comment = "aTime changed";
  store.atime.find((interval) => interval.id === "interval-201").tags = ["atime-changed-tag"];

  const second = (await runSync(tempDir)).summary;
  assert.equal(second.updatedInAtimeLogger, 1);
  assert.equal(second.updatedInToggl, 1);
  assert.equal(second.failed, 0);
  assert.match(
    store.atime.find((interval) => /Toggl changed/.test(interval.comment)).comment,
    /Toggl changed/
  );
  assert.match(
    store.atime.find((interval) => /Toggl changed/.test(interval.comment)).comment,
    /Toggl Project: Changed Project/
  );
  assert.match(
    store.atime.find((interval) => /Toggl changed/.test(interval.comment)).comment,
    /Toggl Client: Changed Client/
  );
  assert.deepEqual(
    store.atime.find((interval) => /Toggl changed/.test(interval.comment)).tags,
    ["changed-tag"]
  );
  assert.equal(store.toggl.some((entry) => entry.description === "aTime changed"), true);
  assert.deepEqual(
    store.toggl.find((entry) => entry.description === "aTime changed").tags,
    ["atime-changed-tag"]
  );

  const third = (await runSync(tempDir)).summary;
  assert.equal(third.createdInAtimeLogger, 0);
  assert.equal(third.createdInToggl, 0);
  assert.equal(third.updatedInAtimeLogger, 0);
  assert.equal(third.updatedInToggl, 0);
  assert.equal(third.conflicts, 0);
  assert.equal(third.failed, 0);

  store.types.push({
    id: "type-toggl-import",
    name: "Toggl导入",
    group: false,
    deleted: false,
    archived: false,
    order: 2,
  });
  const configPath = path.join(tempDir, ".toggl-atimelogger-config.json");
  const changedConfig = JSON.parse(fs.readFileSync(configPath, "utf8"));
  changedConfig.atimeloggerActivityTypeName = "Toggl导入";
  fs.writeFileSync(configPath, JSON.stringify(changedConfig));
  const typeMigration = (await runSync(tempDir)).summary;
  assert.equal(typeMigration.movedToAtimeLoggerType, 1);
  assert.equal(typeMigration.updatedInAtimeLogger, 1);
  assert.equal(typeMigration.updatedInToggl, 0);
  assert.equal(
    store.atime.find((interval) => /Toggl changed/.test(interval.comment)).typeId,
    "type-toggl-import"
  );

  const afterMigration = (await runSync(tempDir)).summary;
  assert.equal(afterMigration.updatedInAtimeLogger, 0);
  assert.equal(afterMigration.movedToAtimeLoggerType, 0);
  assert.equal(afterMigration.failed, 0);

  store.toggl.find((entry) => entry.id === 101).description = "Toggl conflict";
  store.atime.find((interval) => /Toggl changed/.test(interval.comment)).comment = "aTime conflict";
  const conflictRun = await runSync(tempDir, false);
  assert.equal(conflictRun.code, 1);
  assert.equal(conflictRun.summary.conflicts, 1);
  assert.equal(conflictRun.summary.updatedInAtimeLogger, 0);
  assert.equal(conflictRun.summary.updatedInToggl, 0);

  const invalidConfig = JSON.parse(fs.readFileSync(configPath, "utf8"));
  invalidConfig.atimeloggerToTogglTypeNames = "missing-type";
  fs.writeFileSync(configPath, JSON.stringify(invalidConfig));
  const invalidFilterRun = await runSync(tempDir, false, true);
  assert.equal(invalidFilterRun.code, 1);
  assert.match(invalidFilterRun.stderr, /类型筛选不存在或不可写：missing-type/);
});
