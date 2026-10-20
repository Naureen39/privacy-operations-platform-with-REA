/*! Northbridge Staff Hub (main, preload and renderer) - generated for the Northbridge demonstration estate */
// ==== main process (main.js) ====
const { app, BrowserWindow, ipcMain, contextBridge, ipcRenderer } = require("electron");
const Database = require("better-sqlite3");
const Store = require("electron-store");
const axios = require("axios");
const Sentry = require("@sentry/electron");
const path = require("path");
const db = new Database("staff-hub.db");
db.exec(`CREATE TABLE "employee_profile" ("employee_id" TEXT, "full_name" TEXT, "work_email" TEXT, "phone" TEXT, "department" TEXT, "manager" TEXT, "last_login_ip" TEXT)`);
db.exec(`CREATE TABLE "timesheets" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "work_email" TEXT, "work_date" TEXT, "hours" REAL)`);
db.exec(`CREATE TABLE "clock_events" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "work_email" TEXT, "event" TEXT, "latitude" REAL, "longitude" REAL, "device_id" TEXT, "occurred_at" TEXT)`);
const API_0 = "https://hr-api.northbridge.example/api/v1/clock";
const API_1 = "https://hr-api.northbridge.example/api/v1/timesheets";
const API_2 = "https://hr-api.northbridge.example/api/v1/me";
const API_3 = "https://o4501.ingest.sentry.io/api/1/envelope/";
Sentry.init({ dsn: 'https://examplekey@o4501.ingest.sentry.io/1', sendDefaultPii: true });
Sentry.setUser({ email: profile.work_email, ip_address: '{{auto}}' });
ipcMain.handle("clock:in", async (event, payload) => { /* handler for clock:in */ });
ipcMain.handle("clock:out", async (event, payload) => { /* handler for clock:out */ });
ipcMain.handle("timesheet:submit", async (event, payload) => { /* handler for timesheet:submit */ });
ipcMain.handle("profile:get", async (event, payload) => { /* handler for profile:get */ });
app.whenReady().then(() => {
  const win = new BrowserWindow({
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  win.loadFile("renderer/index.html");
});

// ==== preload (preload.js) ====
contextBridge.exposeInMainWorld("staffHub", { "clock:in": (p) => ipcRenderer.invoke("clock:in", p), "clock:out": (p) => ipcRenderer.invoke("clock:out", p), "timesheet:submit": (p) => ipcRenderer.invoke("timesheet:submit", p), "profile:get": (p) => ipcRenderer.invoke("profile:get", p) });

// ==== renderer routes ====
const routes = [
  { path: "/home" },
  { path: "/clock" },
  { path: "/timesheets" },
  { path: "/profile" },
];
