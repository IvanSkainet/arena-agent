const TOKEN = window.ARENA_TOKEN || "";
const BASE = location.origin;
const headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"};
let cmdHistory = JSON.parse(localStorage.getItem("arena_cmd_history") || "[]");
let activeTab = "overview";
let taskRefreshTimer = null;
let overviewMetrics = {requests: 0, execs: 0, errors: 0};

// Reconnection tracking
let wasOffline = false;
let lastConnectedTime = null;

