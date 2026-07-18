// ==UserScript==
// @name         ThreadSieve (Auto)
// @namespace    https://local-only.example/threads-sieve/
// @version      0.4.1
// @description  ThreadSieve captures Threads saved posts and runs the AI-post unsave flow from a single pick-and-run button.
// @author       threads-sieve
// @match        https://threads.com/*
// @match        https://www.threads.com/*
// @match        https://threads.net/*
// @match        https://www.threads.net/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  const STORAGE_KEY = "threadsSavedExportState";
  const SCRIPT_VERSION = "0.4.1";
  const PANEL_ID = "threads-saved-export-panel";
  const FILE_HANDLE_DB = "threadsSavedExportFileDb";
  const FILE_HANDLE_STORE = "handles";
  const FILE_HANDLE_KEY = "catch-json";
  const DEBUG_LOG_FILE_HANDLE_KEY = "threads-debug-log";
  const DEFAULT_SCROLL_DELAY = 1400;
  const UNSAVE_AFTER_LOAD_DELAY_MS = 600;
  const DEFAULT_MAX_PENDING_LOAD_ROUNDS = 8;
  const DEFAULT_MAX_OLD_ONLY_ROUNDS = 1;
  const DEFAULT_MAX_ITEMS = 0;
  const SCROLL_BOTTOM_NUDGE_PX = 260;
  const SCROLL_BOTTOM_NUDGE_DELAY = 180;
  const HIGH_CONFIDENCE_THRESHOLD = 0.85;
  const LOW_CONFIDENCE_THRESHOLD = 0.55;
  const UNSAVE_CLICK_DELAY = 450;
  const UNSAVE_SCROLL_DELAY = 700;
  const UNSAVE_MENU_TIMEOUT = 3500;
  const UNSAVE_MAX_STALLED_ROUNDS = 6;
  const UNSAVE_MAX_BOTTOM_WAIT_ROUNDS = 3;
  const UNSAVE_MAX_FAILURES_PER_KEY = 2;
  const UNSAVE_VIEWPORT_SETTLE_DELAY = 350;
  const UNSAVE_MAX_VIEWPORT_DRAIN_ROUNDS = 6;
  const UNSAVE_MENU_CLOSE_TIMEOUT = 3000;
  const UNSAVE_MAX_NO_NEW_SELECTED_ROUNDS = 200;

  const state = createState();

  const DateUtils = {
    parseTargetDate(value) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) {
        return null;
      }
      const [year, month, day] = value.split("-").map(Number);
      const start = new Date(year, month - 1, day, 0, 0, 0, 0);
      const end = new Date(year, month - 1, day, 23, 59, 59, 999);
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
        return null;
      }
      return {
        raw: value,
        startMs: start.getTime(),
        endMs: end.getTime(),
        label: `${value} (local time)`
      };
    },

    parseDateFromText(text) {
      if (!text) {
        return null;
      }
      const direct = new Date(text);
      if (!Number.isNaN(direct.getTime())) {
        return direct;
      }

      const normalized = text.replace(/\s+/g, " ").trim();
      const monthPattern = /\b([A-Z][a-z]{2,8})\s+(\d{1,2})(?:,\s*(\d{4}))?/;
      const match = normalized.match(monthPattern);
      if (match) {
        const now = new Date();
        const guess = `${match[1]} ${match[2]}, ${match[3] || now.getFullYear()}`;
        const parsed = new Date(guess);
        if (!Number.isNaN(parsed.getTime())) {
          return parsed;
        }
      }

      return null;
    },

    normalizePublishedTime(raw) {
      if (!raw) {
        return { text: "", epochMs: null };
      }
      const parsed = new Date(raw);
      if (!Number.isNaN(parsed.getTime())) {
        return { text: parsed.toISOString(), epochMs: parsed.getTime() };
      }
      const fallback = this.parseDateFromText(raw);
      if (!fallback) {
        return { text: String(raw), epochMs: null };
      }
      return { text: fallback.toISOString(), epochMs: fallback.getTime() };
    },

    isOlderThanTargetRange(epochMs, target) {
      return Boolean(target && Number.isFinite(epochMs) && epochMs < target.startMs);
    },

    isWithinTargetRange(epochMs, target) {
      return Boolean(target && Number.isFinite(epochMs) && epochMs >= target.startMs);
    },

    formatTimestamp(date = new Date()) {
      const pad = (value) => String(value).padStart(2, "0");
      return [
        date.getFullYear(),
        pad(date.getMonth() + 1),
        pad(date.getDate())
      ].join("") + "-" + [
        pad(date.getHours()),
        pad(date.getMinutes()),
        pad(date.getSeconds())
      ].join("");
    }
  };

  const AutoSaveUtils = {
    runtimeHandle: null,
    runtimeHandleWritable: false,

    isSupported() {
      return typeof window.showSaveFilePicker === "function" && typeof indexedDB !== "undefined";
    },

    openDb() {
      return new Promise((resolve, reject) => {
        const request = indexedDB.open(FILE_HANDLE_DB, 1);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(FILE_HANDLE_STORE)) {
            db.createObjectStore(FILE_HANDLE_STORE);
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    },

    async getNamedHandle(key) {
      if (!this.isSupported()) {
        return null;
      }
      const db = await this.openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(FILE_HANDLE_STORE, "readonly");
        const store = tx.objectStore(FILE_HANDLE_STORE);
        const request = store.get(key);
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => reject(request.error);
      });
    },

    async setNamedHandle(key, handle) {
      const db = await this.openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(FILE_HANDLE_STORE, "readwrite");
        const store = tx.objectStore(FILE_HANDLE_STORE);
        const request = store.put(handle, key);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
    },

    async getStoredHandle() {
      return this.getNamedHandle(FILE_HANDLE_KEY);
    },

    async setStoredHandle(handle) {
      return this.setNamedHandle(FILE_HANDLE_KEY, handle);
    },

    async queryPermission(fileHandle, withWrite = true) {
      if (!fileHandle) {
        return "denied";
      }
      const options = withWrite ? { mode: "readwrite" } : {};
      try {
        return await fileHandle.queryPermission(options);
      } catch (_error) {
        return "denied";
      }
    },

    async verifyPermission(fileHandle, withWrite = true, allowPrompt = true) {
      if (!fileHandle) {
        return false;
      }
      const currentState = await this.queryPermission(fileHandle, withWrite);
      if (currentState === "granted") {
        return true;
      }
      if (!allowPrompt) {
        return false;
      }
      const options = withWrite ? { mode: "readwrite" } : {};
      try {
        return (await fileHandle.requestPermission(options)) === "granted";
      } catch (_error) {
        return false;
      }
    },

    async chooseFileHandle() {
      if (!this.isSupported()) {
        throw new Error("目前瀏覽器不支援 File System Access API。");
      }
      const handle = await window.showSaveFilePicker({
        suggestedName: "catch.json",
        types: [
          {
            description: "JSON file",
            accept: {
              "application/json": [".json"]
            }
          }
        ]
      });

      const granted = await this.verifyPermission(handle, true);
      if (!granted) {
        throw new Error("沒有取得寫入權限。");
      }

      await this.setStoredHandle(handle);
      this.runtimeHandle = handle;
      this.runtimeHandleWritable = true;
      state.autoSaveFileName = handle.name || "catch.json";
      state.autoSaveReady = true;
      UI.update();
      return handle;
    },

    async getReadyHandle(options = {}) {
      const { allowPrompt = false } = options;
      if (this.runtimeHandle && this.runtimeHandleWritable) {
        state.autoSaveReady = true;
        state.autoSaveFileName = this.runtimeHandle.name || state.autoSaveFileName || "catch.json";
        return this.runtimeHandle;
      }

      const handle = await this.getStoredHandle();
      if (!handle) {
        state.autoSaveReady = false;
        state.autoSaveFileName = "";
        return null;
      }
      const granted = await this.verifyPermission(handle, true, allowPrompt);
      state.autoSaveReady = granted;
      state.autoSaveFileName = handle.name || "catch.json";
      if (granted) {
        this.runtimeHandle = handle;
        this.runtimeHandleWritable = true;
      }
      return granted ? handle : null;
    },

    async saveItems(items) {
      const jsonText = JSON.stringify(items, null, 2);
      const handle = await this.getReadyHandle({ allowPrompt: false });
      if (!handle) {
        state.autoSaveLastResult = state.autoSaveFileName
          ? "自動存檔未執行：請重新按一次「設定自動存檔」授權"
          : "未設定自動存檔";
        UI.update();
        return false;
      }
      let writable = null;
      try {
        writable = await handle.createWritable();
        await writable.write(jsonText);
        await writable.close();

        const savedFile = await handle.getFile();
        if (jsonText.length > 0 && savedFile.size === 0) {
          throw new Error("寫入後檔案大小仍為 0");
        }
      } catch (error) {
        this.runtimeHandleWritable = false;
        state.autoSaveReady = false;
        if (writable) {
          try {
            await writable.abort();
          } catch (_abortError) {
            // Ignore abort failures and surface the original write error.
          }
        }
        throw error;
      }

      state.autoSaveLastResult = `已寫入 ${handle.name || "catch.json"}`;
      state.autoSaveReady = true;
      UI.update();
      return true;
    },

    async refreshStatus() {
      try {
        if (this.runtimeHandle && this.runtimeHandleWritable) {
          state.autoSaveReady = true;
          state.autoSaveFileName = this.runtimeHandle.name || state.autoSaveFileName || "";
          UI.update();
          return;
        }
        const handle = await this.getStoredHandle();
        state.autoSaveReady = await this.verifyPermission(handle, true, false);
        state.autoSaveFileName = handle?.name || "";
      } catch (_error) {
        state.autoSaveReady = false;
        state.autoSaveFileName = "";
      }
      UI.update();
    }
  };

  const DebugLogUtils = {
    runtimeHandle: null,
    runtimeHandleWritable: false,
    writeQueue: Promise.resolve(),

    async chooseFileHandle() {
      if (!AutoSaveUtils.isSupported()) {
        throw new Error("目前瀏覽器不支援 File System Access API。");
      }
      const handle = await window.showSaveFilePicker({
        suggestedName: "threads-unsave-debug.ndjson",
        types: [
          {
            description: "NDJSON log",
            accept: {
              "application/x-ndjson": [".ndjson"],
              "application/json": [".json"],
              "text/plain": [".log", ".txt"]
            }
          }
        ]
      });
      const granted = await AutoSaveUtils.verifyPermission(handle, true);
      if (!granted) {
        throw new Error("沒有取得 debug log 寫入權限。");
      }
      await AutoSaveUtils.setNamedHandle(DEBUG_LOG_FILE_HANDLE_KEY, handle);
      this.runtimeHandle = handle;
      this.runtimeHandleWritable = true;
      state.debugLogFileName = handle.name || "threads-unsave-debug.ndjson";
      state.debugLogReady = true;
      state.debugLogLastResult = `已設定 debug log: ${state.debugLogFileName}`;
      UI.update();
      return handle;
    },

    async getReadyHandle(options = {}) {
      const { allowPrompt = false } = options;
      if (this.runtimeHandle && this.runtimeHandleWritable) {
        state.debugLogReady = true;
        state.debugLogFileName = this.runtimeHandle.name || state.debugLogFileName || "";
        return this.runtimeHandle;
      }
      const handle = await AutoSaveUtils.getNamedHandle(DEBUG_LOG_FILE_HANDLE_KEY);
      if (!handle) {
        state.debugLogReady = false;
        state.debugLogFileName = "";
        return null;
      }
      const granted = await AutoSaveUtils.verifyPermission(handle, true, allowPrompt);
      state.debugLogReady = granted;
      state.debugLogFileName = handle.name || "threads-unsave-debug.ndjson";
      if (granted) {
        this.runtimeHandle = handle;
        this.runtimeHandleWritable = true;
      }
      return granted ? handle : null;
    },

    async appendEvent(type, payload = {}) {
      this.writeQueue = this.writeQueue
        .catch(() => {})
        .then(() => this._appendEventNow(type, payload));
      return this.writeQueue;
    },

    async _appendEventNow(type, payload = {}) {
      const handle = await this.getReadyHandle({ allowPrompt: false });
      if (!handle) {
        state.debugLogLastResult = state.debugLogFileName
          ? "debug log 未寫入：請重新設定授權"
          : "未設定 debug log";
        UI.update();
        return false;
      }

      const entry = {
        timestamp: new Date().toISOString(),
        type,
        pageUrl: location.href,
        scriptVersion: SCRIPT_VERSION,
        ...payload
      };
      const line = `${JSON.stringify(entry)}\n`;

      let writable = null;
      try {
        const existingFile = await handle.getFile();
        writable = await handle.createWritable({ keepExistingData: true });
        await writable.seek(existingFile.size);
        await writable.write(line);
        await writable.close();
      } catch (error) {
        this.runtimeHandleWritable = false;
        state.debugLogReady = false;
        if (writable) {
          try {
            await writable.abort();
          } catch (_abortError) {
            // Ignore abort failures and surface the original write error.
          }
        }
        state.debugLogLastResult = `debug log 寫入失敗: ${error instanceof Error ? error.message : String(error)}`;
        UI.update();
        return false;
      }

      state.debugLogReady = true;
      state.debugLogLastResult = `已記錄 ${type}`;
      UI.update();
      return true;
    },

    async refreshStatus() {
      try {
        if (this.runtimeHandle && this.runtimeHandleWritable) {
          state.debugLogReady = true;
          state.debugLogFileName = this.runtimeHandle.name || state.debugLogFileName || "";
          UI.update();
          return;
        }
        const handle = await AutoSaveUtils.getNamedHandle(DEBUG_LOG_FILE_HANDLE_KEY);
        state.debugLogReady = await AutoSaveUtils.verifyPermission(handle, true, false);
        state.debugLogFileName = handle?.name || "";
      } catch (_error) {
        state.debugLogReady = false;
        state.debugLogFileName = "";
      }
      UI.update();
    }
  };

  const AiReviewUtils = {
    syncTimerId: 0,
    lastSyncLogSignature: "",

    getUniqueKey(post) {
      return post?.postId || post?.postUrl || "";
    },

    extractPostIdFromUrl(url) {
      const match = String(url || "").match(/\/(?:post|t)\/([^/?#\s]+)/);
      return match ? decodeURIComponent(match[1]) : "";
    },

    normalizeAiItem(item) {
      const confidenceValue = Number(item?.confidence ?? 0);
      const confidence = Number.isFinite(confidenceValue)
        ? Math.max(0, Math.min(1, confidenceValue))
        : 0;
      const decision = String(item?.decision || "unsure").trim().toLowerCase();
      const postUrl = String(item?.postUrl || "");
      const postId = String(item?.postId || this.extractPostIdFromUrl(postUrl));
      return {
        ...item,
        postId,
        postUrl,
        decision: /^(ai|not_ai|unsure)$/.test(decision) ? decision : "unsure",
        confidence
      };
    },

    buildAiMap(items) {
      const map = Object.create(null);
      for (const rawItem of items) {
        const item = this.normalizeAiItem(rawItem);
        if (item.postId) {
          map[item.postId] = item;
        }
        if (item.postUrl) {
          map[item.postUrl] = item;
          const urlKey = this.normalizePostUrlKey(item.postUrl);
          if (urlKey) {
            map[urlKey] = item;
          }
          const postIdFromUrl = this.extractPostIdFromUrl(item.postUrl);
          if (postIdFromUrl) {
            map[postIdFromUrl] = item;
          }
        }
      }
      return map;
    },

    buildAiIndexMap(items) {
      const map = new Map();
      items.forEach((item, index) => {
        if (item.postId) {
          map.set(item.postId, index);
        }
        if (item.postUrl) {
          map.set(item.postUrl, index);
          const urlKey = this.normalizePostUrlKey(item.postUrl);
          if (urlKey) {
            map.set(urlKey, index);
          }
          const postIdFromUrl = this.extractPostIdFromUrl(item.postUrl);
          if (postIdFromUrl) {
            map.set(postIdFromUrl, index);
          }
        }
      });
      return map;
    },

    async loadAiResultsFromHandle(fileHandle) {
      const file = await fileHandle.getFile();
      const payload = JSON.parse(await file.text());
      const sourceItems = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : null;
      if (!sourceItems) {
        throw new Error("unsave 分類格式不正確，找不到 items 陣列。");
      }

      const items = sourceItems.map((item) => this.normalizeAiItem(item));
      state.aiItems = items;
      state.aiMap = this.buildAiMap(items);
      state.aiIndexMap = this.buildAiIndexMap(items);
      const payloadSummary = payload?.summary && typeof payload.summary === "object" ? payload.summary : null;
      state.aiLoadStatus = `已載入 ${items.length} 筆 unsave 分類`;
      state.aiResultFileName = fileHandle.name || "unsave.json";
      state.aiResultGeneratedAt = typeof payload?.generatedAt === "string" ? payload.generatedAt : "";
      state.aiResultBackend = typeof payload?.backend === "string" ? payload.backend : "";
      state.aiResultSourceFile = typeof payload?.sourceFile === "string" ? payload.sourceFile : "";
      state.aiResultSummary = payloadSummary ? { ...payloadSummary } : null;
      state.aiHighlightsActive = false;
      state.selectedAiKeys = new Set();
      state.highlightedKeys = new Set();
      state.unsaveAttemptedKeys = new Set();
      state.unsaveVerifiedKeys = new Set();
      state.unsaveFailedKeys = new Set();
      state.aiReviewStats = createAiReviewStats();
      this.clearHighlights();
      DebugLogUtils.appendEvent("ai_results_loaded", {
        fileName: state.aiResultFileName,
        itemCount: items.length,
        generatedAt: state.aiResultGeneratedAt,
        backend: state.aiResultBackend,
        sourceFile: state.aiResultSourceFile,
        summary: state.aiResultSummary,
        sampleKeys: items.map((item) => item.postId || item.postUrl).filter(Boolean).slice(0, 12)
      }).catch(() => {});
      UI.update();
    },

    getAiItemForPost(post) {
      const urlKey = this.normalizePostUrlKey(post?.postUrl);
      return state.aiMap[post?.postId] ||
        state.aiMap[post?.postUrl] ||
        state.aiMap[urlKey] ||
        this.getLocalAiCandidate(post);
    },

    normalizePostUrlKey(url) {
      if (!url) {
        return "";
      }
      try {
        return new URL(url, location.origin).pathname;
      } catch (_error) {
        const match = String(url).match(/\/(?:post|t)\/[^/?#\s]+/);
        return match ? match[0] : "";
      }
    },

    getLocalAiCandidate(post) {
      const text = [
        post?.contentText || "",
        post?.authorHandle || "",
        post?.authorName || ""
      ].join(" ");
      if (!this.isLikelyAiText(text)) {
        return null;
      }
      return {
        postId: post?.postId || "",
        postUrl: post?.postUrl || "",
        decision: "ai",
        confidence: 0.56,
        reason: "本地關鍵詞判斷為待取消候選；目前載入的 unsave 分類未命中這個 DOM key，可能是瀏覽器載入舊檔或 Threads URL key 不一致。",
        localCandidate: true
      };
    },

    isLikelyAiText(text) {
      const value = String(text || "");
      if (!value.trim()) {
        return false;
      }
      const patterns = [
        /\bAI\b/i,
        /\bA\.I\.\b/i,
        /\bLLM\b/i,
        /\bRAG\b/i,
        /\bMCP\b/i,
        /\bGPT\b/i,
        /\bChatGPT\b/i,
        /\bClaude\b/i,
        /\bCodex\b/i,
        /\bOpenAI\b/i,
        /\bAnthropic\b/i,
        /\bGemini\b/i,
        /\bCursor\b/i,
        /\bCopilot\b/i,
        /\bNotebookLM\b/i,
        /\bLangChain\b/i,
        /\bAgent(?:ic)?\b/i,
        /\bprompt(?:s|ing)?\b/i,
        /\bvibe coding\b/i,
        /人工智慧/,
        /大語言模型/,
        /生成式AI/i,
        /生成 AI/i,
        /AI\s*代理/i,
        /代理程式/,
        /智能體/,
        /提示詞/,
        /工作流/,
        /知識庫/,
        /向量資料庫/,
        /自動化/
      ];
      return patterns.some((pattern) => pattern.test(value));
    },

    getDecisionTier(item) {
      if (!item || item.decision === "not_ai") {
        return "none";
      }
      if (item.decision === "unsure") {
        return "unsure";
      }
      if ((item.confidence || 0) >= HIGH_CONFIDENCE_THRESHOLD) {
        return "high";
      }
      if ((item.confidence || 0) >= LOW_CONFIDENCE_THRESHOLD) {
        return "low";
      }
      return "none";
    },

    countAiItemsByTier() {
      const counts = createAiReviewStats();
      for (const item of state.aiItems) {
        const tier = this.getDecisionTier(item);
        if (tier === "high") {
          counts.highConfidence += 1;
          counts.reviewable += 1;
        } else if (tier === "low") {
          counts.lowConfidence += 1;
          counts.reviewable += 1;
        } else if (tier === "unsure") {
          counts.unsure += 1;
          counts.reviewable += 1;
        }
      }
      return counts;
    },

    getSelectedReviewableItemKeys(tierFilter) {
      const processedKeys = this.getSuppressedKeySet();
      return state.aiItems
        .filter((item) => {
          const tier = this.getDecisionTier(item);
          return typeof tierFilter === "function" ? tierFilter(tier) : tier !== "none";
        })
        .map((item) => item.postId || item.postUrl || this.normalizePostUrlKey(item.postUrl))
        .filter((key) => key && !processedKeys.has(key));
    },

    getHighlightedEntryKeys(entries = this.getLoadedArticleEntries()) {
      const processedKeys = this.getSuppressedKeySet();
      return this.dedupeEntriesByKey(entries)
        .filter((entry) => {
          const tier = this.getDecisionTier(this.getAiItemForPost(entry.post));
          return tier !== "none" && !processedKeys.has(entry.key);
        })
        .map((entry) => entry.key)
        .filter(Boolean);
    },

    addHighlightedEntriesToSelection(entries = this.getLoadedArticleEntries()) {
      let addedCount = 0;
      const processedKeys = this.getSuppressedKeySet();
      for (const entry of this.dedupeEntriesByKey(entries)) {
        const aiItem = this.getAiItemForPost(entry.post);
        if (this.getDecisionTier(aiItem) === "none" || processedKeys.has(entry.key)) {
          continue;
        }
        if (!state.selectedAiKeys.has(entry.key)) {
          state.selectedAiKeys.add(entry.key);
          addedCount += 1;
        }
        this.updateArticleSelectionState(entry.article, entry.key);
      }
      state.aiReviewStats.selected = state.selectedAiKeys.size;
      return addedCount;
    },

    isElementVisible(element) {
      if (!element?.isConnected) {
        return false;
      }
      const rect = element.getBoundingClientRect();
      return rect.width > 0 &&
        rect.height > 0 &&
        rect.bottom > 0 &&
        rect.right > 0 &&
        rect.top < window.innerHeight &&
        rect.left < window.innerWidth;
    },

    getVisibleArticleEntries() {
      return Parser.getArticleNodes()
        .filter((article) => this.isElementVisible(article))
        .map((article) => {
          const post = Parser.parseArticle(article);
          return {
            article,
            post,
            key: this.getUniqueKey(post)
          };
        })
        .filter((entry) => entry.post && entry.key);
    },

    getProcessedKeySet() {
      return new Set([
        ...state.unsaveAttemptedKeys,
        ...state.unsaveVerifiedKeys
      ]);
    },

    getSuppressedKeySet() {
      return new Set([
        ...state.suppressedAiKeys,
        ...state.unsaveAttemptedKeys,
        ...state.unsaveVerifiedKeys
      ]);
    },

    getUnsaveState(key) {
      if (!key) {
        return "";
      }
      if (state.unsaveVerifiedKeys.has(key)) {
        return "verified";
      }
      if (state.unsaveAttemptedKeys.has(key)) {
        return "attempted";
      }
      if (state.unsaveFailedKeys.has(key)) {
        return "failed";
      }
      return "";
    },

    suppressKeys(keys) {
      let changed = false;
      for (const key of keys || []) {
        if (!key || state.suppressedAiKeys.has(key)) {
          continue;
        }
        state.suppressedAiKeys.add(key);
        changed = true;
      }
      if (changed) {
        saveState();
      }
      return changed;
    },

    getLoadedArticleEntries() {
      return Parser.getArticleNodes()
        .map((article) => {
          const post = Parser.parseArticle(article);
          return {
            article,
            post,
            key: this.getUniqueKey(post)
          };
        })
        .filter((entry) => entry.post && entry.key);
    },

    getEntrySignature(entries) {
      if (!entries?.length) {
        return "";
      }
      return entries
        .map((entry) => entry.key)
        .filter(Boolean)
        .join("|");
    },

    clearHighlights(options = {}) {
      const { keepSelection = false, keepActive = false } = options;
      for (const article of Parser.getArticleNodes()) {
        this.clearArticleDecoration(article);
      }
      state.highlightedKeys = new Set();
      if (!keepActive) {
        state.aiHighlightsActive = false;
      }
      if (!keepSelection) {
        state.selectedAiKeys = new Set();
      }
    },

    clearArticleDecoration(article) {
      if (article?.dataset?.aiReviewOriginalPosition !== undefined) {
        article.style.position = article.dataset.aiReviewOriginalPosition || "";
        delete article.dataset.aiReviewOriginalPosition;
      }
      delete article.dataset.aiTier;
      delete article.dataset.aiSelected;
      delete article.dataset.aiMatched;
      delete article.dataset.aiReviewKey;
      delete article.dataset.aiUnsaveState;
      for (const control of article.querySelectorAll("[data-ai-review-control='true']")) {
        control.remove();
      }
    },

    makeBadgeText(aiItem, tier) {
      if (aiItem.localCandidate) {
        return "本地候選";
      }
      return aiItem.decision === "unsure" ? "待確認" : "待取消";
    },

    getOutcomeText(key) {
      const stateText = this.getUnsaveState(key);
      if (stateText === "verified") {
        return "已驗證取消儲存";
      }
      if (stateText === "attempted") {
        return "已點擊，待重新整理確認";
      }
      if (stateText === "failed") {
        return "本輪執行失敗";
      }
      return "";
    },

    ensureReviewAnchor(article) {
      if (!article || article.dataset.aiReviewOriginalPosition !== undefined) {
        return;
      }
      article.dataset.aiReviewOriginalPosition = article.style.position || "";
      if (window.getComputedStyle(article).position === "static") {
        article.style.position = "relative";
      }
    },

    createReviewControl(entry, aiItem, tier) {
      const control = document.createElement("div");
      control.dataset.aiReviewControl = "true";
      control.className = `${PANEL_ID}-review-control`;
      const stopHostClick = (event, options = {}) => {
        if (options.preventDefault) {
          event.preventDefault();
        }
        event.stopPropagation();
      };
      const isCheckboxTarget = (event) => event.target === checkbox || event.target?.closest?.("[data-ai-review-checkbox='true']");

      const topRow = document.createElement("div");
      topRow.className = `${PANEL_ID}-review-row`;

      const toggleLabel = document.createElement("label");
      toggleLabel.className = `${PANEL_ID}-review-toggle`;

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.aiReviewCheckbox = "true";
      checkbox.checked = state.selectedAiKeys.has(entry.key);
      checkbox.addEventListener("click", (event) => stopHostClick(event));
      checkbox.addEventListener("change", () => this.setSelection(entry.key, entry.article, checkbox.checked));

      const badge = document.createElement("span");
      badge.className = `${PANEL_ID}-review-badge`;
      badge.dataset.aiTier = tier;
      badge.textContent = this.makeBadgeText(aiItem, tier);

      const nonCheckboxToggleHandler = (event) => {
        if (isCheckboxTarget(event)) {
          stopHostClick(event);
          return;
        }
        stopHostClick(event, { preventDefault: true });
        this.toggleSelection(entry.key, entry.article);
      };
      const hostShieldHandler = (event) => {
        if (isCheckboxTarget(event)) {
          stopHostClick(event);
          return;
        }
        stopHostClick(event, { preventDefault: true });
      };

      control.addEventListener("click", nonCheckboxToggleHandler);
      control.addEventListener("mousedown", hostShieldHandler);
      control.addEventListener("mouseup", hostShieldHandler);
      control.addEventListener("pointerdown", hostShieldHandler);
      control.addEventListener("pointerup", hostShieldHandler);
      toggleLabel.addEventListener("mousedown", hostShieldHandler);
      toggleLabel.addEventListener("mouseup", hostShieldHandler);

      toggleLabel.appendChild(checkbox);
      toggleLabel.appendChild(badge);
      topRow.appendChild(toggleLabel);

      if (aiItem.reason) {
        const reason = document.createElement("div");
        reason.className = `${PANEL_ID}-review-reason`;
        reason.textContent = aiItem.reason;
        control.appendChild(topRow);
        control.appendChild(reason);
      } else {
        control.appendChild(topRow);
      }

      const outcomeText = this.getOutcomeText(entry.key);
      if (outcomeText) {
        const outcome = document.createElement("div");
        outcome.className = `${PANEL_ID}-review-outcome`;
        outcome.dataset.unsaveState = this.getUnsaveState(entry.key);
        outcome.textContent = outcomeText;
        control.appendChild(outcome);
      }

      return control;
    },

    dedupeEntriesByKey(entries) {
      const uniqueEntries = [];
      const seen = new Set();
      for (const entry of entries) {
        if (!entry?.key || seen.has(entry.key)) {
          continue;
        }
        seen.add(entry.key);
        uniqueEntries.push(entry);
      }
      return uniqueEntries;
    },

    recordProgressFailure(progress, key) {
      if (!progress.failedKeys.includes(key)) {
        progress.failedKeys.push(key);
      }
      progress.failed = progress.failedKeys.length;
    },

    clearProgressFailure(progress, key) {
      progress.failedKeys = progress.failedKeys.filter((failedKey) => failedKey !== key);
      progress.failed = progress.failedKeys.length;
    },

    extractDiagnosticKey(value) {
      const text = String(value || "").trim();
      if (!text) {
        return "";
      }
      const postMatch = text.match(/\/post\/([^/?#\s]+)/);
      if (postMatch) {
        return postMatch[1];
      }
      return text.replace(/^@[^/\s]+\/post\//, "").replace(/[,\s]+$/g, "");
    },

    resolveAiItemByKey(key) {
      const normalizedKey = this.extractDiagnosticKey(key);
      if (!normalizedKey) {
        return null;
      }
      const exactItem = state.aiMap[normalizedKey];
      if (exactItem) {
        return exactItem;
      }
      return state.aiItems.find((item) => {
        const postId = item.postId || "";
        const postUrl = item.postUrl || "";
        return postId === normalizedKey ||
          postUrl === normalizedKey ||
          postId.startsWith(normalizedKey) ||
          postUrl.includes(normalizedKey);
      }) || null;
    },

    diagnoseAiKeys() {
      const rawInput = window.prompt("輸入要診斷的 postId 或 URL，可用換行、逗號或空白分隔。", "");
      if (rawInput === null) {
        return;
      }
      const keys = rawInput
        .split(/[\s,]+/)
        .map((value) => this.extractDiagnosticKey(value))
        .filter(Boolean);
      if (keys.length === 0) {
        setError("沒有輸入可診斷的 postId 或 URL。");
        return;
      }

      const loadedEntries = this.getLoadedArticleEntries();
      const visibleEntries = this.getVisibleArticleEntries();
      const diagnostics = keys.map((key) => {
        const item = this.resolveAiItemByKey(key);
        const resolvedKey = item ? (item.postId || item.postUrl || key) : key;
        const loadedEntry = loadedEntries.find((entry) => entry.key === resolvedKey || entry.key.startsWith(resolvedKey));
        const visibleEntry = visibleEntries.find((entry) => entry.key === resolvedKey || entry.key.startsWith(resolvedKey));
        return {
          input: key,
          resolvedKey,
          aiIndex: state.aiIndexMap.get(resolvedKey) ?? null,
          decision: item?.decision || null,
          confidence: item?.confidence ?? null,
          tier: this.getDecisionTier(item),
          selected: state.selectedAiKeys.has(resolvedKey),
          suppressed: state.suppressedAiKeys.has(resolvedKey),
          unsaveState: this.getUnsaveState(resolvedKey),
          loadedInDom: Boolean(loadedEntry),
          visible: Boolean(visibleEntry),
          postUrl: item?.postUrl || ""
        };
      });

      DebugLogUtils.appendEvent("ai_key_diagnostics", {
        selectedCount: state.selectedAiKeys.size,
        suppressedCount: state.suppressedAiKeys.size,
        visibleEntries: visibleEntries.map((entry) => entry.key).slice(0, 20),
        diagnostics
      }).catch(() => {});
      setError(`已寫入 ${diagnostics.length} 筆分類 key 診斷到 debug log。`);
      UI.update();
    },

    getActionableVisibleSelectedEntries(progress, visibleEntries = this.getVisibleArticleEntries()) {
      return this.dedupeEntriesByKey(visibleEntries)
        .filter((entry) => state.selectedAiKeys.has(entry.key))
        .filter((entry) => !progress.processedKeys.has(entry.key))
        .filter((entry) => (progress.failedAttemptsByKey.get(entry.key) || 0) < UNSAVE_MAX_FAILURES_PER_KEY);
    },

    resolveVisibleEntryByKey(key) {
      return this.getVisibleArticleEntries()
        .find((entry) => entry.key === key) || null;
    },

    updateArticleSelectionState(article, key) {
      const isSelected = state.selectedAiKeys.has(key);
      article.dataset.aiSelected = isSelected ? "true" : "false";
      const checkbox = article.querySelector("[data-ai-review-checkbox='true']");
      if (checkbox) {
        checkbox.checked = isSelected;
      }
    },

    setSelection(key, article, selected) {
      if (selected) {
        state.selectedAiKeys.add(key);
      } else {
        state.selectedAiKeys.delete(key);
      }
      this.updateArticleSelectionState(article, key);
      state.aiReviewStats.selected = state.selectedAiKeys.size;
      UI.update();
    },

    toggleSelection(key, article) {
      this.setSelection(key, article, !state.selectedAiKeys.has(key));
    },

    applyHighlights() {
      if (state.aiItems.length === 0) {
        setError("請先載入 unsave.json。");
        return;
      }

      state.aiHighlightsActive = true;
      const processedKeys = this.getSuppressedKeySet();
      state.selectedAiKeys = new Set(this.getSelectedReviewableItemKeys((tier) => tier === "high"));
      this.syncHighlights();
      state.aiLoadStatus = `標亮已啟用（總選取 ${state.selectedAiKeys.size} 筆；目前 DOM 隨捲動同步）`;
      const itemCounts = this.countAiItemsByTier();
      DebugLogUtils.appendEvent("ai_highlights_activated", {
        selectedCount: state.selectedAiKeys.size,
        totalReviewable: itemCounts.reviewable,
        renderedMatched: state.aiReviewStats.renderedMatched,
        processedCount: processedKeys.size
      }).catch(() => {});
      setError("");
      UI.update();
    },

    syncHighlights() {
      if (!state.aiHighlightsActive || state.aiItems.length === 0) {
        return;
      }

      const entries = this.getLoadedArticleEntries();
      const decoratedKeys = new Set();
      const stats = createAiReviewStats();

      for (const entry of entries) {
        const aiItem = this.getAiItemForPost(entry.post);
        const tier = this.getDecisionTier(aiItem);
        if (!aiItem || tier === "none") {
          this.clearArticleDecoration(entry.article);
          continue;
        }

        stats.renderedMatched += 1;
        stats.reviewable += 1;
        if (tier === "high") {
          stats.highConfidence += 1;
        } else if (tier === "low") {
          stats.lowConfidence += 1;
        } else if (tier === "unsure") {
          stats.unsure += 1;
        }
        if (aiItem.localCandidate) {
          stats.localCandidate += 1;
        }

        const previousKey = entry.article.dataset.aiReviewKey || "";
        const previousTier = entry.article.dataset.aiTier || "";
        const previousUnsaveState = entry.article.dataset.aiUnsaveState || "";
        const currentUnsaveState = this.getUnsaveState(entry.key);
        decoratedKeys.add(entry.key);
        const existingControl = entry.article.querySelector("[data-ai-review-control='true']");
        const needsRebuild = !existingControl ||
          previousKey !== entry.key ||
          previousTier !== tier ||
          previousUnsaveState !== currentUnsaveState;
        this.ensureReviewAnchor(entry.article);
        if (needsRebuild) {
          if (existingControl) {
            existingControl.remove();
          }
          const control = this.createReviewControl(entry, aiItem, tier);
          entry.article.prepend(control);
        }
        entry.article.dataset.aiTier = tier;
        entry.article.dataset.aiMatched = "true";
        entry.article.dataset.aiReviewKey = entry.key;
        entry.article.dataset.aiUnsaveState = currentUnsaveState;
        this.updateArticleSelectionState(entry.article, entry.key);
      }

      state.highlightedKeys = decoratedKeys;
      stats.selected = state.selectedAiKeys.size;
      state.aiReviewStats = stats;
      this.logSyncDiagnostics(entries, stats);
      UI.update();
    },

    scheduleSync() {
      if (!state.aiHighlightsActive || state.aiItems.length === 0) {
        return;
      }
      if (this.syncTimerId) {
        window.clearTimeout(this.syncTimerId);
      }
      this.syncTimerId = window.setTimeout(() => {
        this.syncTimerId = 0;
        this.syncHighlights();
      }, 120);
    },

    logSyncDiagnostics(entries, stats) {
      const signature = `${this.getEntrySignature(entries)}::${stats.renderedMatched}`;
      if (!state.debugLogReady || signature === this.lastSyncLogSignature) {
        return;
      }
      this.lastSyncLogSignature = signature;
      const unmatchedEntries = entries
        .filter((entry) => !this.getAiItemForPost(entry.post))
        .slice(0, 6)
        .map((entry) => ({
          key: entry.key,
          postId: entry.post?.postId || "",
          postUrl: entry.post?.postUrl || "",
          text: (entry.post?.contentText || "").replace(/\s+/g, " ").slice(0, 120)
        }));
      DebugLogUtils.appendEvent("ai_sync_snapshot", {
        scriptVersion: SCRIPT_VERSION,
        loadedEntries: entries.length,
        renderedMatched: stats.renderedMatched,
        selectedCount: state.selectedAiKeys.size,
        totalReviewable: this.countAiItemsByTier().reviewable,
        loadedFileName: state.aiResultFileName,
        loadedGeneratedAt: state.aiResultGeneratedAt,
        loadedSummary: state.aiResultSummary,
        localCandidateMatched: stats.localCandidate,
        visibleSignature: this.getEntrySignature(entries).slice(0, 240),
        unmatchedEntries
      }).catch(() => {});
    },

    selectHighConfidence() {
      if (!state.aiHighlightsActive) {
        this.applyHighlights();
        return;
      }

      const processedKeys = this.getSuppressedKeySet();
      state.selectedAiKeys = new Set(this.getSelectedReviewableItemKeys((tier) => tier === "high"));
      this.syncHighlights();
      state.aiReviewStats.selected = state.selectedAiKeys.size;
      if (state.selectedAiKeys.size === 0) {
        setError("目前沒有建議取消的貼文。");
      } else {
        setError("");
      }
      UI.update();
    },

    findMoreButton(article) {
      const scopes = [article, article.parentElement].filter(Boolean);
      for (const scope of scopes) {
        const svgs = Array.from(scope.querySelectorAll('svg[aria-label="更多"], svg[aria-label="More"]'));
        for (const svg of svgs) {
          const button = svg.closest("[role='button'], button");
          if (!button) {
            continue;
          }
          if (button.closest("[data-ai-review-control='true']")) {
            continue;
          }
          if (button.closest("header")) {
            continue;
          }
          // when searching parent scope, skip buttons that belong to a different article
          if (scope !== article) {
            const ownerArticle = button.closest("article");
            if (ownerArticle && ownerArticle !== article) {
              continue;
            }
          }
          return button;
        }
      }
      return this.findSpatialMoreButton(article);
    },

    findSpatialMoreButton(article) {
      if (!article?.isConnected) {
        return null;
      }
      const articleRect = article.getBoundingClientRect();
      const articleCenterY = articleRect.top + Math.min(Math.max(articleRect.height * 0.25, 32), 96);
      const candidates = Array.from(document.querySelectorAll('svg[aria-label="更多"], svg[aria-label="More"]'))
        .map((svg) => svg.closest("[role='button'], button"))
        .filter((button) => {
          if (!button || button.closest("[data-ai-review-control='true']") || button.closest("header")) {
            return false;
          }
          const ownerArticle = button.closest("article");
          if (ownerArticle && ownerArticle !== article) {
            return false;
          }
          return this.isElementVisible(button);
        })
        .map((button) => {
          const rect = button.getBoundingClientRect();
          const centerY = rect.top + rect.height / 2;
          const withinVerticalBand = centerY >= articleRect.top - 120 && centerY <= articleRect.bottom + 120;
          return {
            button,
            withinVerticalBand,
            score: Math.abs(centerY - articleCenterY) + Math.abs(rect.right - articleRect.right) * 0.15
          };
        })
        .filter((candidate) => candidate.withinVerticalBand)
        .sort((left, right) => left.score - right.score);
      return candidates[0]?.button || null;
    },

    normalizeMenuItemText(text) {
      return (text || "").replace(/\s+/g, " ").trim();
    },

    findUnsaveMenuItem() {
      const items = Array.from(document.querySelectorAll("[role='menuitem']"));
      const exactMatches = [];
      const looseMatches = [];
      for (const item of items) {
        if (!item?.isConnected) {
          continue;
        }
        const text = this.normalizeMenuItemText(item.textContent);
        if (text === "取消儲存" || text === "Unsave") {
          exactMatches.push(item);
          continue;
        }
        if (/取消儲存|unsave/i.test(text)) {
          looseMatches.push(item);
        }
      }
      const visibleExact = exactMatches.find((item) => this.isElementVisible(item));
      if (visibleExact) {
        return visibleExact;
      }
      if (exactMatches[0]) {
        return exactMatches[0];
      }
      const visibleLoose = looseMatches.find((item) => this.isElementVisible(item));
      if (visibleLoose) {
        return visibleLoose;
      }
      if (looseMatches[0]) {
        return looseMatches[0];
      }
      return null;
    },

    collectVisibleMenuItemTexts(limit = 8) {
      return Array.from(document.querySelectorAll("[role='menuitem']"))
        .filter((item) => this.isElementVisible(item))
        .slice(0, limit)
        .map((item) => item.textContent.replace(/\s+/g, " ").trim())
        .filter(Boolean);
    },

    collectMoreButtonDiagnostics(article) {
      const articleSvgs = Array.from(article.querySelectorAll('svg[aria-label="更多"], svg[aria-label="More"]'));
      const articleButtons = articleSvgs
        .map((svg) => svg.closest("[role='button'], button"))
        .filter(Boolean);
      const parentEl = article.parentElement;
      const parentSvgs = parentEl
        ? Array.from(parentEl.querySelectorAll('svg[aria-label="更多"], svg[aria-label="More"]'))
        : [];
      const parentButtons = parentSvgs
        .map((svg) => svg.closest("[role='button'], button"))
        .filter(Boolean);
      const globalButtons = Array.from(document.querySelectorAll('svg[aria-label="更多"], svg[aria-label="More"]'))
        .map((svg) => svg.closest("[role='button'], button"))
        .filter(Boolean);
      const articleRect = article.getBoundingClientRect();
      const spatialCandidates = globalButtons
        .filter((button) => this.isElementVisible(button))
        .map((button) => {
          const rect = button.getBoundingClientRect();
          return {
            label: this.describeButton(button).label,
            top: Math.round(rect.top),
            right: Math.round(rect.right),
            ownerArticleMatches: button.closest("article") === article
          };
        })
        .filter((candidate) => candidate.top >= articleRect.top - 160 && candidate.top <= articleRect.bottom + 160)
        .slice(0, 6);

      return {
        articleMoreSvgCount: articleSvgs.length,
        articleMoreButtonCount: articleButtons.length,
        articleMoreButtonLabels: articleButtons
          .slice(0, 4)
          .map((button) => this.describeButton(button).label)
          .filter(Boolean),
        parentMoreSvgCount: parentSvgs.length,
        parentMoreButtonCount: parentButtons.length,
        globalMoreButtonCount: globalButtons.length,
        globalHeaderMoreButtonCount: globalButtons.filter((button) => button.closest("header")).length,
        articleRect: {
          top: Math.round(articleRect.top),
          bottom: Math.round(articleRect.bottom),
          right: Math.round(articleRect.right),
          height: Math.round(articleRect.height)
        },
        spatialCandidates
      };
    },

    describeButton(button) {
      if (!button) {
        return {
          exists: false,
          label: "",
          pressed: null,
          disabled: false,
          hasSavedLabel: false,
          hasUnsavedLabel: false,
          isClearlySaved: false,
          isClearlyUnsaved: false
        };
      }
      const label = [
        button.getAttribute("aria-label"),
        button.getAttribute("title"),
        button.querySelector("svg[aria-label]")?.getAttribute("aria-label"),
        button.textContent
      ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim().toLowerCase();
      const ariaPressed = button.getAttribute("aria-pressed");
      const pressed = ariaPressed === "true" ? true : ariaPressed === "false" ? false : null;
      const disabled = button.getAttribute("disabled") !== null || button.getAttribute("aria-disabled") === "true";
      const hasSavedLabel = /remove from saved|unsave|移除收藏|取消儲存|(^|\s)saved(\s|$)|已儲存/.test(label);
      const hasUnsavedLabel = !hasSavedLabel && /add to saved|save post|(^|\s)save(\s|$)|加入收藏|收藏|(^|\s)儲存(\s|$)/.test(label);
      const isClearlySaved = pressed === true || hasSavedLabel;
      const isClearlyUnsaved = pressed === false || hasUnsavedLabel;
      return {
        exists: true,
        label,
        pressed,
        disabled,
        hasSavedLabel,
        hasUnsavedLabel,
        isClearlySaved,
        isClearlyUnsaved
      };
    },

    triggerElementClick(element) {
      if (!element) {
        return;
      }
      const eventOptions = { bubbles: true, cancelable: true, view: window };
      const PointerCtor = window.PointerEvent || window.MouseEvent;
      element.dispatchEvent(new PointerCtor("pointerdown", eventOptions));
      element.dispatchEvent(new MouseEvent("mousedown", eventOptions));
      element.dispatchEvent(new PointerCtor("pointerup", eventOptions));
      element.dispatchEvent(new MouseEvent("mouseup", eventOptions));
      element.click();
    },

    async waitForUnsaveMenuItem(timeout = UNSAVE_MENU_TIMEOUT) {
      const startedAt = Date.now();
      while (Date.now() - startedAt < timeout) {
        const item = this.findUnsaveMenuItem();
        if (item) {
          return item;
        }
        await wait(100);
      }
      return null;
    },

    async waitForMenuToClose(timeout = UNSAVE_MENU_CLOSE_TIMEOUT) {
      const startedAt = Date.now();
      while (Date.now() - startedAt < timeout) {
        if (!this.findUnsaveMenuItem()) {
          return true;
        }
        await wait(100);
      }
      return false;
    },

    closeOpenMenu() {
      document.body?.click();
    },

    async waitForUnsaveEffect(entry) {
      const startedAt = Date.now();
      while (Date.now() - startedAt < 2500) {
        if (!entry.article?.isConnected) {
          return "verified";
        }
        const currentButton = this.findMoreButton(entry.article);
        if (!currentButton) {
          return "verified";
        }
        await wait(200);
      }
      return "attempted";
    },

    markUnsaveOutcome(key, outcome) {
      state.unsaveAttemptedKeys.delete(key);
      state.unsaveVerifiedKeys.delete(key);
      state.unsaveFailedKeys.delete(key);
      if (outcome === "verified") {
        state.unsaveVerifiedKeys.add(key);
        this.suppressKeys([key]);
      } else if (outcome === "attempted") {
        state.unsaveAttemptedKeys.add(key);
      } else if (outcome === "failed") {
        state.unsaveFailedKeys.add(key);
      }
    },

    async processVisibleSelectedEntries(entries, progress) {
      for (const queuedEntry of this.dedupeEntriesByKey(entries)) {
        const entry = this.resolveVisibleEntryByKey(queuedEntry.key);
        if (!entry) {
          DebugLogUtils.appendEvent("unsave_item_deferred", {
            key: queuedEntry.key,
            reason: "not_visible_after_refresh"
          }).catch(() => {});
          continue;
        }
        const currentFailureCount = progress.failedAttemptsByKey.get(entry.key) || 0;
        if (progress.processedKeys.has(entry.key) || currentFailureCount >= UNSAVE_MAX_FAILURES_PER_KEY) {
          continue;
        }
        try {
          entry.article.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
          await wait(120);
          const button = this.findMoreButton(entry.article);
          if (!button) {
            const nextFailureCount = currentFailureCount + 1;
            progress.failedAttemptsByKey.set(entry.key, nextFailureCount);
            this.recordProgressFailure(progress, entry.key);
            this.markUnsaveOutcome(entry.key, "failed");
            if (nextFailureCount >= UNSAVE_MAX_FAILURES_PER_KEY) {
              progress.processedKeys.add(entry.key);
            }
            DebugLogUtils.appendEvent("unsave_item_failed", {
              key: entry.key,
              reason: "button_not_found",
              stage: "more_button",
              diagnostics: this.collectMoreButtonDiagnostics(entry.article),
              failureCount: nextFailureCount
            }).catch(() => {});
            continue;
          }
          const beforeState = this.describeButton(button);
          if (beforeState.disabled) {
            const nextFailureCount = currentFailureCount + 1;
            progress.failedAttemptsByKey.set(entry.key, nextFailureCount);
            this.recordProgressFailure(progress, entry.key);
            this.markUnsaveOutcome(entry.key, "failed");
            progress.processedKeys.add(entry.key);
            DebugLogUtils.appendEvent("unsave_item_failed", {
              key: entry.key,
              reason: "button_disabled",
              buttonState: beforeState,
              failureCount: nextFailureCount
            }).catch(() => {});
            continue;
          }
          this.triggerElementClick(button);
          const unsaveItem = await this.waitForUnsaveMenuItem();
          if (!unsaveItem) {
            const nextFailureCount = currentFailureCount + 1;
            progress.failedAttemptsByKey.set(entry.key, nextFailureCount);
            this.closeOpenMenu();
            this.recordProgressFailure(progress, entry.key);
            this.markUnsaveOutcome(entry.key, "failed");
            if (nextFailureCount >= UNSAVE_MAX_FAILURES_PER_KEY) {
              progress.processedKeys.add(entry.key);
            }
            DebugLogUtils.appendEvent("unsave_item_failed", {
              key: entry.key,
              reason: "menuitem_not_found",
              stage: "unsave_menuitem",
              buttonState: beforeState,
              visibleMenuItems: this.collectVisibleMenuItemTexts(),
              failureCount: nextFailureCount
            }).catch(() => {});
            await wait(UNSAVE_CLICK_DELAY);
            continue;
          }

          const menuItemText = this.normalizeMenuItemText(unsaveItem.textContent);
          this.triggerElementClick(unsaveItem);

          const menuClosed = await this.waitForMenuToClose();
          if (!menuClosed) {
            DebugLogUtils.appendEvent("unsave_menu_still_open", {
              key: entry.key,
              buttonState: beforeState,
              menuItemText
            }).catch(() => {});
          }

          const outcome = await this.waitForUnsaveEffect(entry);
          this.markUnsaveOutcome(entry.key, outcome);
          this.clearProgressFailure(progress, entry.key);
          progress.processedKeys.add(entry.key);
          state.selectedAiKeys.delete(entry.key);
          DebugLogUtils.appendEvent("unsave_item_result", {
            key: entry.key,
            outcome,
            buttonStateBefore: beforeState,
            menuItemText
          }).catch(() => {});
          if (outcome === "verified") {
            progress.verified += 1;
          } else {
            progress.attempted += 1;
          }
          this.syncHighlights();
          setStatus(
            `取消儲存進行中: 已驗證 ${progress.verified} / 待刷新 ${progress.attempted} / 失敗 ${state.unsaveFailedKeys.size} / 剩餘 ${state.selectedAiKeys.size}`
          );
          await wait(UNSAVE_CLICK_DELAY);
        } catch (_error) {
          const nextFailureCount = currentFailureCount + 1;
          progress.failedAttemptsByKey.set(entry.key, nextFailureCount);
          this.recordProgressFailure(progress, entry.key);
          this.markUnsaveOutcome(entry.key, "failed");
          if (nextFailureCount >= UNSAVE_MAX_FAILURES_PER_KEY) {
            progress.processedKeys.add(entry.key);
          }
          DebugLogUtils.appendEvent("unsave_item_failed", {
            key: entry.key,
            reason: "exception",
            failureCount: nextFailureCount
          }).catch(() => {});
        }
      }
    },

    async runUnsaveFromPickedFile() {
      if (typeof window.showOpenFilePicker !== "function") {
        setError("目前瀏覽器不支援載入本機 JSON 檔案。");
        return;
      }
      if (!isLikelySavedPage()) {
        setError("請先切到 Threads 收藏頁（/saved）再執行取消儲存。");
        return;
      }
      let fileHandle;
      try {
        [fileHandle] = await window.showOpenFilePicker({
          multiple: false,
          types: [
            {
              description: "AI classification JSON",
              accept: {
                "application/json": [".json"]
              }
            }
          ]
        });
      } catch (error) {
        if (error?.name !== "AbortError") {
          setError(`選擇 unsave.json 失敗: ${error instanceof Error ? error.message : String(error)}`);
        }
        return;
      }
      await this.loadAiResultsFromHandle(fileHandle);
      // 選檔即宣告「此檔為當前真相」：清掉歷次累積的排除鍵，避免舊的
      // 誤判 verified（Threads 虛擬捲動造成的 article detach）永久吃掉候選。
      // 已真正取消的貼文不會出現在頁面上，巡覽迴圈會自行略過。
      if (state.suppressedAiKeys.size > 0) {
        state.suppressedAiKeys = new Set();
        saveState();
      }
      try {
        this.applyHighlights();
        await wait(UNSAVE_AFTER_LOAD_DELAY_MS);
        this.selectHighConfidence();
        if (state.selectedAiKeys.size === 0) {
          setError("沒有建議取消的貼文，未執行取消儲存。");
          return;
        }
        await this.unsaveSelected();
      } finally {
        // 一鍵流程結束即停用標亮同步；否則 MutationObserver 與
        // syncHighlights/UI.update 的 DOM 寫入互相觸發，形成無限重繪迴圈。
        this.clearHighlights();
        UI.update();
      }
    },

    async unsaveSelected({ skipConfirm = false } = {}) {
      if (state.aiHighlightsActive) {
        this.syncHighlights();
        const addedHighlightedCount = this.addHighlightedEntriesToSelection();
        if (addedHighlightedCount > 0) {
          DebugLogUtils.appendEvent("unsave_visible_highlights_auto_selected", {
            addedHighlightedCount,
            selectedCount: state.selectedAiKeys.size,
            highlightedKeys: this.getHighlightedEntryKeys().slice(0, 20),
            phase: "start"
          }).catch(() => {});
        }
      }

      if (state.selectedAiKeys.size === 0) {
        setError("目前沒有已選取的貼文可取消儲存。");
        return;
      }

      const selectedCount = state.selectedAiKeys.size;
      if (!skipConfirm) {
        const confirmed = window.confirm(
          `即將自動從頁面頂部往下巡覽，取消儲存 ${selectedCount} 篇已選取貼文。\nThreads 頁面通常不會立即反映結果，腳本會把已點擊的貼文標記為待重新整理確認。是否繼續？`
        );
        if (!confirmed) {
          return;
        }
      }

      setError("");
      state.unsaveFailedKeys = new Set();
      const selectedAiIndexes = Array.from(state.selectedAiKeys)
        .map((key) => state.aiIndexMap.get(key))
        .filter((index) => Number.isInteger(index));
      let hasUnindexedSelectedKeys = state.selectedAiKeys.size > selectedAiIndexes.length;
      const maxSelectedAiIndex = selectedAiIndexes.length > 0 ? Math.max(...selectedAiIndexes) : -1;
      const selectedTierCounts = Array.from(state.selectedAiKeys).reduce((counts, key) => {
        const visibleEntry = this.resolveVisibleEntryByKey(key);
        const item = this.resolveAiItemByKey(key) || (visibleEntry ? this.getAiItemForPost(visibleEntry.post) : null);
        const tier = this.getDecisionTier(item);
        counts[tier] = (counts[tier] || 0) + 1;
        return counts;
      }, {});
      const visibleEntriesAtStart = this.getVisibleArticleEntries();
      DebugLogUtils.appendEvent("unsave_run_started", {
        selectedCount,
        visibleEntries: visibleEntriesAtStart.length,
        visibleHighlightedCount: this.getHighlightedEntryKeys(visibleEntriesAtStart).length,
        visibleSelectedCount: visibleEntriesAtStart.filter((entry) => state.selectedAiKeys.has(entry.key)).length,
        selectedSampleKeys: Array.from(state.selectedAiKeys).slice(0, 20),
        selectedTierCounts,
        hasUnindexedSelectedKeys,
        selectedIndexMin: selectedAiIndexes.length > 0 ? Math.min(...selectedAiIndexes) : null,
        selectedIndexMax: maxSelectedAiIndex >= 0 ? maxSelectedAiIndex : null
      }).catch(() => {});
      const progress = {
        verified: 0,
        attempted: 0,
        failed: 0,
        failedKeys: [],
        processedKeys: new Set(),
        failedAttemptsByKey: new Map(),
        seenVisibleSelectedKeys: new Set()
      };
      const scrollContainer = Scroller.getScrollContainer();
      Scroller.scrollToStart(scrollContainer);
      await wait(UNSAVE_SCROLL_DELAY);

      let maxSeenAiIndex = -1;
      let aiOrderBoundaryLogged = false;
      let stalledRounds = 0;
      let bottomWaitRounds = 0;
      let consecutiveNoNewSelectedRounds = 0;
      let stopReason = "completed";
      while (state.selectedAiKeys.size > 0) {
        this.syncHighlights();
        const autoAddedInRound = state.aiHighlightsActive ? this.addHighlightedEntriesToSelection() : 0;
        if (autoAddedInRound > 0) {
          hasUnindexedSelectedKeys = true;
          DebugLogUtils.appendEvent("unsave_visible_highlights_auto_selected", {
            addedHighlightedCount: autoAddedInRound,
            selectedCount: state.selectedAiKeys.size,
            highlightedKeys: this.getHighlightedEntryKeys().slice(0, 20),
            phase: "scroll"
          }).catch(() => {});
        }
        const visibleEntries = this.getVisibleArticleEntries();
        const beforeSignature = this.getEntrySignature(visibleEntries);
        const beforeMetrics = Scroller.getScrollMetrics(scrollContainer);
        const visibleSelectedEntries = this.dedupeEntriesByKey(visibleEntries)
          .filter((entry) => state.selectedAiKeys.has(entry.key));
        for (const entry of visibleEntries) {
          const aiIndex = state.aiIndexMap.get(entry.key);
          if (Number.isInteger(aiIndex)) {
            maxSeenAiIndex = Math.max(maxSeenAiIndex, aiIndex);
          }
        }

        const prevSeenCount = progress.seenVisibleSelectedKeys.size;
        for (const entry of visibleSelectedEntries) {
          progress.seenVisibleSelectedKeys.add(entry.key);
        }
        if (progress.seenVisibleSelectedKeys.size > prevSeenCount) {
          consecutiveNoNewSelectedRounds = 0;
        } else if (visibleSelectedEntries.length === 0) {
          consecutiveNoNewSelectedRounds += 1;
          if (consecutiveNoNewSelectedRounds >= UNSAVE_MAX_NO_NEW_SELECTED_ROUNDS) {
            stopReason = "no_progress";
            break;
          }
        }
        if (visibleSelectedEntries.length === 0
            && maxSelectedAiIndex >= 0
            && !hasUnindexedSelectedKeys
            && maxSeenAiIndex > maxSelectedAiIndex
            && !aiOrderBoundaryLogged) {
          aiOrderBoundaryLogged = true;
          DebugLogUtils.appendEvent("unsave_ai_order_boundary_seen", {
            remainingSelected: state.selectedAiKeys.size,
            seenSelectedCount: progress.seenVisibleSelectedKeys.size,
            visibleEntryKeys: visibleEntries.map((entry) => entry.key).slice(0, 20),
            maxSelectedAiIndex,
            maxSeenAiIndex
          }).catch(() => {});
          stopReason = "ai_order_boundary_no_selected";
          break;
        }

        let selectedEntries = this.getActionableVisibleSelectedEntries(progress, visibleEntries);

        if (selectedEntries.length > 0) {
          let drainRounds = 0;
          while (selectedEntries.length > 0 && drainRounds < UNSAVE_MAX_VIEWPORT_DRAIN_ROUNDS) {
            await this.processVisibleSelectedEntries(selectedEntries, progress);
            stalledRounds = 0;
            bottomWaitRounds = 0;
            drainRounds += 1;

            await wait(UNSAVE_VIEWPORT_SETTLE_DELAY);
            this.syncHighlights();

            const refreshedVisibleEntries = this.getVisibleArticleEntries();
            const refreshedSelectedEntries = this.getActionableVisibleSelectedEntries(progress, refreshedVisibleEntries);
            if (refreshedSelectedEntries.length === 0) {
              break;
            }

            for (const entry of this.dedupeEntriesByKey(refreshedVisibleEntries).filter((item) => state.selectedAiKeys.has(item.key))) {
              progress.seenVisibleSelectedKeys.add(entry.key);
            }

            DebugLogUtils.appendEvent("unsave_viewport_pending_after_process", {
              pendingCount: refreshedSelectedEntries.length,
              drainRounds,
              keys: refreshedSelectedEntries.map((entry) => entry.key).slice(0, 12)
            }).catch(() => {});
            selectedEntries = refreshedSelectedEntries;
          }
          stalledRounds = 0;
          bottomWaitRounds = 0;
        }

        if (state.selectedAiKeys.size === 0) {
          break;
        }

        const atBottom = beforeMetrics.top + beforeMetrics.client >= beforeMetrics.height - 8;
        if (atBottom) {
          Scroller.scrollToEnd(scrollContainer);
        } else {
          Scroller.scrollByStep(scrollContainer);
        }

        await wait(UNSAVE_SCROLL_DELAY);
        this.syncHighlights();

        const afterVisibleEntries = this.getVisibleArticleEntries();
        const afterSignature = this.getEntrySignature(afterVisibleEntries);
        const afterMetrics = Scroller.getScrollMetrics(scrollContainer);
        const scrollAdvanced = afterMetrics.top > beforeMetrics.top || afterMetrics.height > beforeMetrics.height;
        const viewportChanged = afterSignature !== beforeSignature;

        if (scrollAdvanced || viewportChanged) {
          stalledRounds = 0;
          bottomWaitRounds = 0;
          continue;
        }

        stalledRounds += 1;
        if (atBottom) {
          bottomWaitRounds += 1;
        }

        DebugLogUtils.appendEvent("unsave_scroll_stalled", {
          remainingSelected: state.selectedAiKeys.size,
          stalledRounds,
          bottomWaitRounds,
          atBottom,
          beforeSignature,
          afterSignature,
          beforeMetrics,
          afterMetrics,
          visibleSelectedCount: selectedEntries.length,
          visibleEntryCount: visibleEntries.length
        }).catch(() => {});

        if (bottomWaitRounds >= UNSAVE_MAX_BOTTOM_WAIT_ROUNDS) {
          stopReason = "bottom_stalled";
          break;
        }
        if (stalledRounds >= UNSAVE_MAX_STALLED_ROUNDS) {
          stopReason = "scroll_stalled";
          break;
        }
      }

      let reconciledMissingKeys = [];
      if ((stopReason === "bottom_stalled" || stopReason === "no_progress" || stopReason === "ai_order_boundary_no_selected")
          && state.selectedAiKeys.size > 0) {
        reconciledMissingKeys = Array.from(state.selectedAiKeys)
          .filter((key) => !progress.seenVisibleSelectedKeys.has(key));
        if (reconciledMissingKeys.length > 0) {
          DebugLogUtils.appendEvent("unsave_missing_keys_reconciled", {
            count: reconciledMissingKeys.length,
            persisted: false,
            selectedCleared: false,
            keys: reconciledMissingKeys.slice(0, 20)
          }).catch(() => {});
        }
      }

      const finalFailedKeys = Array.from(state.unsaveFailedKeys);
      const finalFailedCount = finalFailedKeys.length;
      state.aiReviewStats.selected = state.selectedAiKeys.size;
      this.syncHighlights();
      const summary = `取消儲存完成: ${progress.verified} 已驗證 / ${progress.attempted} 已點擊待刷新 / ${finalFailedCount} 失敗`;
      setStatus(summary);
      DebugLogUtils.appendEvent("unsave_run_finished", {
        summary,
        verified: progress.verified,
        attempted: progress.attempted,
        failed: finalFailedCount,
        remainingSelected: state.selectedAiKeys.size,
        failedKeys: finalFailedKeys,
        stopReason,
        reconciledMissingCount: reconciledMissingKeys.length
      }).catch(() => {});
      if (state.selectedAiKeys.size > 0) {
        setError(`${summary}。仍有 ${state.selectedAiKeys.size} 篇未執行，可能尚未捲到、或按鈕未成功辨識。`);
      } else if (finalFailedKeys.length > 0) {
        setError(`${summary}。找不到按鈕或點擊失敗: ${finalFailedKeys.slice(0, 3).join(", ")}${finalFailedKeys.length > 3 ? "..." : ""}`);
      } else {
        setError("");
      }
      UI.update();
    }
  };

  const Parser = {
    getPostLinkNodes(root = document) {
      const selector = 'a[href*="/post/"], a[href*="/t/"]';
      const seed = root?.matches?.(selector) ? [root] : [];
      const candidates = seed.concat(Array.from(root.querySelectorAll(selector)));
      const seen = new Set();

      return candidates.filter((link) => {
        const href = this.normalizePostHref(link.getAttribute("href"));
        if (!href || seen.has(href)) {
          return false;
        }
        seen.add(href);
        return true;
      });
    },

    normalizePostHref(href) {
      if (!href) {
        return "";
      }
      try {
        return new URL(href, location.origin).pathname;
      } catch (_error) {
        return String(href).trim();
      }
    },

    stripInjectedReviewUi(root) {
      if (!root?.querySelectorAll) {
        return root;
      }
      for (const control of root.querySelectorAll("[data-ai-review-control='true']")) {
        control.remove();
      }
      return root;
    },

    cloneWithoutReviewUi(root) {
      if (!root?.cloneNode) {
        return root;
      }
      return this.stripInjectedReviewUi(root.cloneNode(true));
    },

    getArticleNodes() {
      const articles = Array.from(document.querySelectorAll("article"))
        .filter((article) => Boolean(this.findPostLink(article)));
      if (articles.length > 0) {
        return articles;
      }
      return this.getFallbackPostContainers();
    },

    getFallbackPostContainers() {
      const containers = [];
      const seen = new Set();

      for (const postLink of this.getPostLinkNodes()) {
        const container = this.findPostContainer(postLink);
        if (!container || seen.has(container)) {
          continue;
        }
        seen.add(container);
        containers.push(container);
      }

      return containers;
    },

    findPostContainer(postLink) {
      const targetHref = this.normalizePostHref(postLink.getAttribute("href"));
      const candidates = [];

      for (let element = postLink.parentElement; element && element !== document.body; element = element.parentElement) {
        const postLinks = this.getPostLinkNodes(element);
        const postHrefs = postLinks
          .map((link) => this.normalizePostHref(link.getAttribute("href")))
          .filter(Boolean);
        const uniquePostCount = postHrefs.length;
        const containsTarget = postHrefs.includes(targetHref);
        const textLength = (element.innerText || "").replace(/\s+/g, " ").trim().length;
        const hasTime = Boolean(element.querySelector("time, [datetime]"));
        const authorLinkCount = element.querySelectorAll('a[href^="/@"]').length;

        if (containsTarget && uniquePostCount === 1 && textLength >= 20) {
          candidates.push({
            element,
            uniquePostCount,
            textLength,
            hasTime,
            authorLinkCount
          });
        }
        if (containsTarget && uniquePostCount > 1 && uniquePostCount <= 4 && textLength >= 20) {
          candidates.push({
            element,
            uniquePostCount,
            textLength,
            hasTime,
            authorLinkCount
          });
        }
      }

      if (candidates.length > 0) {
        candidates.sort((a, b) => {
          const score = (item) => {
            const linkPenalty = item.uniquePostCount * 220;
            const authorPenalty = Math.max(0, item.authorLinkCount - 1) * 80;
            const timeBonus = item.hasTime ? 120 : 0;
            return item.textLength + timeBonus - linkPenalty - authorPenalty;
          };

          return score(b) - score(a);
        });
        return candidates[0].element;
      }

      return postLink.closest("div, li, section");
    },

    inspectDom() {
      const articleNodes = this.getArticleNodes();
      const postLinks = this.getPostLinkNodes();
      const timeNodes = Array.from(document.querySelectorAll("time"));
      const datetimeNodes = Array.from(document.querySelectorAll("[datetime]"));
      const firstArticleText = articleNodes[0]?.innerText?.replace(/\s+/g, " ").trim() || "";

      return {
        articleCount: articleNodes.length,
        containerSource: Array.from(document.querySelectorAll("article")).length > 0 ? "article" : "link-fallback",
        postLinkCount: postLinks.length,
        timeNodeCount: timeNodes.length,
        datetimeCount: datetimeNodes.length,
        samplePostHref: postLinks[0]?.getAttribute("href") || "",
        sampleTimeText: timeNodes[0]?.getAttribute("datetime") || timeNodes[0]?.textContent?.trim() || "",
        sampleArticleText: firstArticleText.slice(0, 140)
      };
    },

    collectPosts() {
      const articles = this.getArticleNodes();
      const posts = [];
      const diagnostics = this.inspectDom();
      diagnostics.parsedPostCount = 0;
      diagnostics.nullPostCount = 0;
      diagnostics.parseErrorCount = 0;
      diagnostics.emptyContentCount = 0;
      diagnostics.emptyContentExamples = [];
      diagnostics.lastNullReason = "";

      for (const article of articles) {
        try {
          const post = this.parseArticle(article);
          if (post) {
            posts.push(post);
            diagnostics.parsedPostCount += 1;
            if (!post.contentText) {
              diagnostics.emptyContentCount += 1;
              if (diagnostics.emptyContentExamples.length < 3) {
                diagnostics.emptyContentExamples.push({
                  postUrl: post.postUrl || "",
                  authorHandle: post.authorHandle || "",
                  publishedTime: post.publishedTime || "",
                  articlePreview: (article.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160)
                });
              }
            }
          } else {
            diagnostics.nullPostCount += 1;
            diagnostics.lastNullReason = this.explainNullArticle(article);
          }
        } catch (error) {
          diagnostics.parseErrorCount += 1;
          state.lastError = `Parse error: ${error instanceof Error ? error.message : String(error)}`;
        }
      }

      state.debug = diagnostics;
      return posts;
    },

    parseArticle(article) {
      const postLink = this.findPostLink(article);
      const postUrl = postLink ? new URL(postLink.getAttribute("href"), location.origin).toString() : "";
      const postId = this.extractPostId(postUrl) || article.getAttribute("data-id") || "";
      const { authorHandle, authorName } = this.extractAuthor(article, postUrl);
      let contentText = this.extractContent(article, authorHandle, authorName);
      if (this.isWeakContentText(contentText)) {
        const expandedContent = this.extractExpandedContent(article, postLink, authorHandle, authorName, contentText);
        if (this.isBetterContentCandidate(expandedContent, contentText)) {
          contentText = expandedContent;
        }
      }
      const publishedRaw = this.extractPublishedTime(article, postLink, postUrl);
      const published = DateUtils.normalizePublishedTime(publishedRaw);

      if (!postUrl && !contentText) {
        return null;
      }

      return {
        postId: postId || postUrl || this.makeContentHash(contentText),
        postUrl,
        authorHandle,
        authorName,
        contentText,
        publishedTime: published.text,
        publishedEpochMs: published.epochMs,
        collectedAt: new Date().toISOString(),
        sourcePage: location.href
      };
    },

    findPostLink(article) {
      const selectors = [
        'a[href*="/post/"]',
        'a[href*="/t/"]',
        'a[role="link"][href*="/"]'
      ];
      const candidates = [];

      for (const selector of selectors) {
        const links = Array.from(article.querySelectorAll(selector));
        for (const link of links) {
          const href = link.getAttribute("href") || "";
          if (!/\/post\/|\/t\//.test(href)) {
            continue;
          }
          candidates.push(link);
        }
      }

      if (candidates.length === 0) {
        return null;
      }

      const scored = candidates.map((link, index) => {
        const dateNode = link.querySelector("time, [datetime]");
        const rawValue = this.readDateNodeValue(dateNode) || link.textContent?.trim() || "";
        const parsed = DateUtils.normalizePublishedTime(rawValue);

        return {
          link,
          index,
          hasDateNode: Boolean(dateNode),
          epochMs: parsed.epochMs
        };
      });

      scored.sort((a, b) => {
        const dateNodeDelta = Number(b.hasDateNode) - Number(a.hasDateNode);
        if (dateNodeDelta !== 0) {
          return dateNodeDelta;
        }

        return a.index - b.index;
      });

      return scored[0].link;
    },

    extractPostId(url) {
      if (!url) {
        return "";
      }
      const match = url.match(/\/(?:post|t)\/([^/?#]+)/);
      return match ? match[1] : "";
    },

    readDateNodeValue(node) {
      if (!node) {
        return "";
      }
      return node.getAttribute("datetime") || node.textContent?.trim() || "";
    },

    isLikelyTimestampText(text) {
      const value = String(text || "").trim();
      if (!value) {
        return false;
      }

      return /^(?:just now|now|today|yesterday)$/i.test(value) ||
        /^(?:今天|昨天|昨日|剛剛)$/.test(value) ||
        /^\d{1,2}:\d{2}(?:\s?[ap]m)?$/i.test(value) ||
        /^\d{4}-\d{1,2}-\d{1,2}$/.test(value) ||
        /^\d{1,2}\/\d{1,2}(?:\/\d{2,4})?$/.test(value) ||
        /^\d{1,2}月\d{1,2}日$/.test(value) ||
        /^\d+\/\d+$/.test(value) ||
        /^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?$/i.test(value) ||
        /^\d+\s*(?:s|sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|wk|wks|week|weeks|mo|mos|month|months|y|yr|yrs|year|years)(?:\s+ago)?$/i.test(value) ||
        /^\d+\s*(?:秒|分鐘|分|小時|天|週|周|月|個月|年)(?:前)?$/.test(value);
    },

    isIgnoredText(text) {
      const value = String(text || "").trim();
      if (!value) {
        return true;
      }
      return /^(@|Reply|Like|Repost|Share|Follow|Following|Saved)$/i.test(value) ||
        /^\d{1,3}(?:,\d{3})*$/.test(value) ||
        this.isLikelyTimestampText(value);
    },

    normalizeIdentityText(text) {
      return String(text || "")
        .trim()
        .replace(/^@/, "")
        .toLowerCase();
    },

    isHandleLikeText(text, authorHandle) {
      const normalizedText = this.normalizeIdentityText(text);
      const normalizedHandle = this.normalizeIdentityText(authorHandle);
      return Boolean(normalizedText && normalizedHandle && normalizedText === normalizedHandle);
    },

    isWeakContentText(text) {
      const value = String(text || "").trim();
      if (!value) {
        return true;
      }
      if (value.includes("\n")) {
        return false;
      }
      return value.length <= 24 && /^[\p{L}\p{N}_.#@ -]+$/u.test(value);
    },

    isBetterContentCandidate(nextText, currentText) {
      const current = String(currentText || "").trim();
      const next = String(nextText || "").trim();
      if (!next) {
        return false;
      }
      if (!current) {
        return true;
      }
      const currentScore = current.length + (current.includes("\n") ? 80 : 0);
      const nextScore = next.length + (next.includes("\n") ? 80 : 0);
      return nextScore > currentScore + 20;
    },

    extractAuthor(article, postUrl) {
      const handleFromUrl = (() => {
        if (!postUrl) {
          return "";
        }
        const match = postUrl.match(/threads\.(?:com|net)\/@?([^/]+)\/(?:post|t)\//);
        return match ? `@${match[1].replace(/^@/, "")}` : "";
      })();

      const profileLink = Array.from(article.querySelectorAll('a[href^="/@"]')).find((link) => {
        const href = link.getAttribute("href") || "";
        return /^\/@[^/]+$/.test(href);
      });

      const authorHandle = handleFromUrl || (profileLink ? profileLink.textContent.trim() : "");
      const profileSpanText = profileLink?.querySelector("span")?.textContent?.trim() || "";
      const authorName = profileLink?.getAttribute("title") ||
        (!this.isHandleLikeText(profileSpanText, authorHandle) ? profileSpanText : "");

      return {
        authorHandle: authorHandle || "",
        authorName: this.isHandleLikeText(authorName, authorHandle) ? "" : (authorName || "")
      };
    },

    findLikelyAuthorName(article, authorHandle) {
      const texts = this.collectTextCandidates(article);
      return texts.find((text) => {
        return text &&
          text !== authorHandle &&
          !text.startsWith("@") &&
          !this.isHandleLikeText(text, authorHandle) &&
          !this.isIgnoredText(text);
      }) || "";
    },

    sanitizeContentLines(lines, authorHandle = "", authorName = "") {
      return lines
        .map((part) => part.trim())
        .filter((part) => part.length > 0)
        .filter((part) => !this.isIgnoredText(part))
        .filter((part) => !this.isHandleLikeText(part, authorHandle))
        .filter((part) => !this.isHandleLikeText(part, authorName))
        .filter((part) => part !== authorName);
    },

    extractContentFromContainer(container, authorHandle = "", authorName = "") {
      const cleanContainer = this.cloneWithoutReviewUi(container);
      const primaryTextWrapper = Array.from(cleanContainer.querySelectorAll('[data-testid="post-text"]'))
        .find((node) => !node.closest("a"));
      if (primaryTextWrapper) {
        const wrapperLines = this.sanitizeContentLines(
          (primaryTextWrapper.innerText || "").split("\n"),
          authorHandle,
          authorName
        );
        if (wrapperLines.length > 0) {
          return wrapperLines.join("\n").trim();
        }
      }

      const dirAutoLeafLines = this.sanitizeContentLines(
        Array.from(cleanContainer.querySelectorAll('[dir="auto"]'))
          .filter((node) => !node.closest("a"))
          .filter((node) => !node.closest("time"))
          .filter((node) => !node.querySelector('[dir="auto"]'))
          .flatMap((node) => (node.textContent || "").split("\n")),
        authorHandle,
        authorName
      );
      if (dirAutoLeafLines.length > 0) {
        return dirAutoLeafLines.join("\n").trim();
      }

      const rawLines = (cleanContainer.innerText || "")
        .split("\n")
        .map((part) => part.trim())
        .filter((part) => part.length > 0);

      const headerLine = rawLines[0] || "";
      const filteredLines = this.sanitizeContentLines(rawLines, authorHandle, authorName);

      if (filteredLines.length > 1 && headerLine && headerLine.includes(filteredLines[0])) {
        filteredLines.shift();
      }

      return filteredLines.join("\n").trim();
    },

    extractContent(article, authorHandle = "", authorName = "") {
      return this.extractContentFromContainer(article, authorHandle, authorName);
    },

    extractExpandedContent(article, postLink, authorHandle = "", authorName = "", currentContent = "") {
      const targetHref = this.normalizePostHref(postLink?.getAttribute("href") || "");
      let best = currentContent;

      for (let element = article.parentElement; element && element !== document.body; element = element.parentElement) {
        const uniquePostHrefs = Array.from(new Set(
          this.getPostLinkNodes(element)
            .map((link) => this.normalizePostHref(link.getAttribute("href")))
            .filter(Boolean)
        ));

        if (!targetHref || !uniquePostHrefs.includes(targetHref)) {
          continue;
        }
        if (uniquePostHrefs.length > 12) {
          break;
        }

        const candidate = this.extractContentFromContainer(element, authorHandle, authorName);
        if (this.isBetterContentCandidate(candidate, best)) {
          best = candidate;
        }
      }

      return best;
    },

    extractPublishedTime(article, postLink, postUrl) {
      const targetHref = this.normalizePostHref(postUrl || postLink?.getAttribute("href") || "");

      if (postLink) {
        const directTimeNode = postLink.querySelector("time, [datetime]");
        const directValue = this.readDateNodeValue(directTimeNode);
        if (directValue) {
          return directValue;
        }
      }

      if (targetHref) {
        const exactPostAnchors = Array.from(article.querySelectorAll("a")).filter((link) => {
          return this.normalizePostHref(link.getAttribute("href")) === targetHref;
        });

        for (const anchor of exactPostAnchors) {
          const timeNode = anchor.querySelector("time, [datetime]");
          const value = this.readDateNodeValue(timeNode);
          if (value) {
            return value;
          }
        }
      }

      const candidateDateNodes = Array.from(article.querySelectorAll("time, [datetime]"))
        .filter((node) => {
          const anchor = node.closest("a");
          const anchorHref = this.normalizePostHref(anchor?.getAttribute("href") || "");
          if (!targetHref || !anchorHref) {
            return true;
          }
          return anchorHref === targetHref || !/\/(?:post|t)\//.test(anchorHref);
        })
        .map((node) => {
          const value = this.readDateNodeValue(node);
          const parsed = DateUtils.normalizePublishedTime(value);
          return {
            value,
            epochMs: parsed.epochMs
          };
        })
        .filter((item) => Boolean(item.value));

      const bestCandidate = candidateDateNodes
        .sort((a, b) => (b.epochMs || 0) - (a.epochMs || 0))[0];
      if (bestCandidate?.value) {
        return bestCandidate.value;
      }

      const linkWithTime = Array.from(article.querySelectorAll("a")).find((link) => {
        const href = this.normalizePostHref(link.getAttribute("href") || "");
        if (targetHref && href && href !== targetHref && /\/(?:post|t)\//.test(href)) {
          return false;
        }
        const text = link.textContent?.trim() || "";
        return Boolean(DateUtils.parseDateFromText(text));
      });

      return linkWithTime?.textContent?.trim() || "";
    },

    collectTextCandidates(article) {
      const cleanArticle = this.cloneWithoutReviewUi(article);
      return Array.from(cleanArticle.querySelectorAll("span, div, a"))
        .map((node) => node.textContent?.trim() || "")
        .filter(Boolean)
        .filter((text) => !this.isIgnoredText(text))
        .filter((text) => text.length < 80);
    },

    explainNullArticle(article) {
      const hasPostLink = Boolean(this.findPostLink(article));
      const contentText = this.extractContent(article);
      const publishedRaw = this.extractPublishedTime(article);
      const preview = (article.innerText || "").replace(/\s+/g, " ").trim().slice(0, 100);

      return JSON.stringify({
        hasPostLink,
        hasContentText: Boolean(contentText),
        hasPublishedRaw: Boolean(publishedRaw),
        preview
      });
    },

    makeContentHash(value) {
      let hash = 0;
      for (let index = 0; index < value.length; index += 1) {
        hash = (hash << 5) - hash + value.charCodeAt(index);
        hash |= 0;
      }
      return `content-${Math.abs(hash)}`;
    }
  };

  const UI = {
    elements: {},

    init() {
      this.injectStyles();
      this.render();
      this.bindEvents();
      this.update();
    },

    injectStyles() {
      if (document.getElementById(`${PANEL_ID}-style`)) {
        return;
      }
      const style = document.createElement("style");
      style.id = `${PANEL_ID}-style`;
      style.textContent = `
        #${PANEL_ID} {
          position: fixed;
          top: 16px;
          right: 16px;
          z-index: 999999;
          width: 320px;
          max-height: calc(100vh - 32px);
          overflow-y: auto;
          overscroll-behavior: contain;
          background: rgba(18, 18, 18, 0.94);
          color: #f7f7f7;
          border: 1px solid rgba(255, 255, 255, 0.14);
          border-radius: 14px;
          box-shadow: 0 12px 28px rgba(0, 0, 0, 0.35);
          padding: 14px;
          font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          backdrop-filter: blur(8px);
        }
        #${PANEL_ID} * { box-sizing: border-box; }
        #${PANEL_ID} h2 {
          margin: 0 0 10px;
          font-size: 14px;
          font-weight: 700;
        }
        #${PANEL_ID} .row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          margin-bottom: 8px;
        }
        #${PANEL_ID} .full {
          display: block;
          width: 100%;
          margin-bottom: 8px;
        }
        #${PANEL_ID} label {
          display: block;
          margin-bottom: 4px;
          font-size: 12px;
          color: #c9c9c9;
        }
        #${PANEL_ID} input,
        #${PANEL_ID} button {
          width: 100%;
          border-radius: 10px;
          border: 1px solid rgba(255, 255, 255, 0.15);
          background: rgba(255, 255, 255, 0.08);
          color: #fff;
          padding: 9px 10px;
          font: inherit;
        }
        #${PANEL_ID} input[type="checkbox"] {
          width: auto;
          margin-right: 6px;
        }
        #${PANEL_ID} button {
          cursor: pointer;
          transition: background 120ms ease;
        }
        #${PANEL_ID} button:hover {
          background: rgba(255, 255, 255, 0.16);
        }
        #${PANEL_ID} button[disabled] {
          opacity: 0.55;
          cursor: not-allowed;
        }
        #${PANEL_ID} .actions {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          margin-top: 10px;
        }
        #${PANEL_ID} .unsave-run {
          margin-top: 10px;
          padding: 14px 12px;
          font-size: 15px;
          font-weight: 700;
          border: 1px solid rgba(255, 107, 107, 0.55);
          background: rgba(214, 48, 49, 0.82);
        }
        #${PANEL_ID} .unsave-run:hover {
          background: rgba(231, 76, 60, 0.95);
        }
        #${PANEL_ID} details {
          margin-top: 10px;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
          padding-top: 8px;
        }
        #${PANEL_ID} summary {
          cursor: pointer;
          color: #e8e8e8;
          font-weight: 600;
          list-style-position: inside;
        }
        #${PANEL_ID} .meta {
          margin-top: 10px;
          padding: 10px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.05);
          white-space: pre-line;
          max-height: 34vh;
          overflow-y: auto;
        }
        #${PANEL_ID} .hint,
        #${PANEL_ID} .error {
          margin-top: 8px;
          font-size: 12px;
        }
        #${PANEL_ID} .error { color: #ffb0b0; }
        #${PANEL_ID} .hint { color: #c9c9c9; }
        #${PANEL_ID} .checkbox-line {
          display: flex;
          align-items: center;
          gap: 6px;
          margin: 6px 0 2px;
        }
        [data-ai-matched="true"][data-ai-tier="high"] {
          outline: 3px solid #ff8a00 !important;
          outline-offset: 3px;
        }
        [data-ai-matched="true"][data-ai-tier="low"] {
          outline: 2px solid #f4c15d !important;
          outline-offset: 3px;
        }
        [data-ai-matched="true"][data-ai-tier="unsure"] {
          outline: 2px dashed #9aa0a6 !important;
          outline-offset: 3px;
        }
        [data-ai-matched="true"][data-ai-selected="true"] {
          box-shadow: 0 0 0 4px rgba(255, 138, 0, 0.18) !important;
        }
        .${PANEL_ID}-review-control {
          position: absolute;
          top: 8px;
          left: 8px;
          right: 8px;
          z-index: 4;
          margin: 0;
          padding: 8px 10px;
          border-radius: 12px;
          border: 1px solid rgba(255, 255, 255, 0.12);
          background: rgba(12, 12, 12, 0.72);
          color: #f7f7f7;
          font: 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          backdrop-filter: blur(6px);
          box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28);
          max-width: min(320px, calc(100% - 16px));
        }
        .${PANEL_ID}-review-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .${PANEL_ID}-review-toggle {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
        }
        .${PANEL_ID}-review-toggle input[type="checkbox"] {
          margin: 0;
        }
        .${PANEL_ID}-review-badge {
          display: inline-flex;
          align-items: center;
          min-height: 28px;
          padding: 4px 10px;
          border-radius: 999px;
          font-weight: 700;
          letter-spacing: 0.01em;
        }
        .${PANEL_ID}-review-badge[data-ai-tier="high"] {
          background: rgba(255, 138, 0, 0.22);
          color: #ffd5a3;
        }
        .${PANEL_ID}-review-badge[data-ai-tier="low"] {
          background: rgba(244, 193, 93, 0.2);
          color: #ffe7b0;
        }
        .${PANEL_ID}-review-badge[data-ai-tier="unsure"] {
          background: rgba(154, 160, 166, 0.2);
          color: #e3e6e8;
        }
        .${PANEL_ID}-review-reason {
          margin-top: 6px;
          color: #d7d7d7;
          white-space: pre-wrap;
          max-height: 4.2em;
          overflow: hidden;
        }
        .${PANEL_ID}-review-outcome {
          margin-top: 6px;
          font-size: 12px;
          font-weight: 600;
        }
        .${PANEL_ID}-review-outcome[data-unsave-state="verified"] {
          color: #9fe3b1;
        }
        .${PANEL_ID}-review-outcome[data-unsave-state="attempted"] {
          color: #8fd6ff;
        }
        .${PANEL_ID}-review-outcome[data-unsave-state="failed"] {
          color: #ffb0b0;
        }
      `;
      document.head.appendChild(style);
    },

    render() {
      if (document.getElementById(PANEL_ID)) {
        return;
      }

      const panel = document.createElement("section");
      panel.id = PANEL_ID;
      panel.innerHTML = `
        <h2>ThreadSieve</h2>
        <label for="${PANEL_ID}-date">截止日期</label>
        <input id="${PANEL_ID}-date" class="full" type="date" />
        <div class="row">
          <div>
            <label for="${PANEL_ID}-max">最大抓取筆數</label>
            <input id="${PANEL_ID}-max" type="number" min="0" step="1" placeholder="0 = 不限制" />
          </div>
          <div>
            <label for="${PANEL_ID}-delay">滾動延遲 ms</label>
            <input id="${PANEL_ID}-delay" type="number" min="300" step="100" />
          </div>
        </div>
        <label class="checkbox-line">
          <input id="${PANEL_ID}-new-only" type="checkbox" />
          <span>僅抓取新項目</span>
        </label>
        <div class="actions">
          <button id="${PANEL_ID}-start">開始抓取</button>
          <button id="${PANEL_ID}-stop">停止</button>
          <button id="${PANEL_ID}-autosave">設定自動存檔</button>
          <button id="${PANEL_ID}-clear">清空結果</button>
        </div>
        <div id="${PANEL_ID}-meta" class="meta"></div>
        <div id="${PANEL_ID}-error" class="error"></div>
        <button id="${PANEL_ID}-unsave-run" class="unsave-run">取消儲存</button>
        <details>
          <summary>診斷</summary>
          <div class="actions">
            <button id="${PANEL_ID}-diagnose-ai-keys">診斷指定貼文</button>
            <button id="${PANEL_ID}-debug-log">設定 Debug Log</button>
          </div>
          <div id="${PANEL_ID}-debug-meta" class="meta"></div>
        </details>
        <div class="hint">只會處理目前瀏覽器已登入且實際載入到頁面的收藏貼文。</div>
      `;

      document.body.appendChild(panel);

      this.elements = {
        panel,
        cutoffDate: panel.querySelector(`#${PANEL_ID}-date`),
        maxItems: panel.querySelector(`#${PANEL_ID}-max`),
        delay: panel.querySelector(`#${PANEL_ID}-delay`),
        newOnly: panel.querySelector(`#${PANEL_ID}-new-only`),
        start: panel.querySelector(`#${PANEL_ID}-start`),
        stop: panel.querySelector(`#${PANEL_ID}-stop`),
        autosave: panel.querySelector(`#${PANEL_ID}-autosave`),
        clear: panel.querySelector(`#${PANEL_ID}-clear`),
        unsaveRun: panel.querySelector(`#${PANEL_ID}-unsave-run`),
        diagnoseAiKeys: panel.querySelector(`#${PANEL_ID}-diagnose-ai-keys`),
        debugLog: panel.querySelector(`#${PANEL_ID}-debug-log`),
        meta: panel.querySelector(`#${PANEL_ID}-meta`),
        debugMeta: panel.querySelector(`#${PANEL_ID}-debug-meta`),
        error: panel.querySelector(`#${PANEL_ID}-error`)
      };

      this.elements.cutoffDate.value = state.cutoffDate;
      this.elements.maxItems.value = state.maxItems ? String(state.maxItems) : "";
      this.elements.delay.value = String(state.scrollDelay);
      this.elements.newOnly.checked = state.onlyNew;
    },

    bindEvents() {
      this.elements.cutoffDate.addEventListener("change", () => {
        state.cutoffDate = this.elements.cutoffDate.value;
        saveState();
        this.update();
      });

      this.elements.maxItems.addEventListener("change", () => {
        const value = Number(this.elements.maxItems.value || 0);
        state.maxItems = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
        saveState();
        this.update();
      });

      this.elements.delay.addEventListener("change", () => {
        const value = Number(this.elements.delay.value || DEFAULT_SCROLL_DELAY);
        state.scrollDelay = Math.max(300, Number.isFinite(value) ? Math.floor(value) : DEFAULT_SCROLL_DELAY);
        saveState();
        this.update();
      });

      this.elements.newOnly.addEventListener("change", () => {
        state.onlyNew = this.elements.newOnly.checked;
        saveState();
        this.update();
      });

      this.elements.start.addEventListener("click", () => Scroller.start());
      this.elements.stop.addEventListener("click", () => Scroller.stop("已停止"));
      this.elements.autosave.addEventListener("click", async () => {
        try {
          await AutoSaveUtils.chooseFileHandle();
          state.autoSaveLastResult = `已設定自動存檔: ${state.autoSaveFileName || "catch.json"}`;
          UI.update();
        } catch (error) {
          setError(`自動存檔設定失敗: ${error instanceof Error ? error.message : String(error)}`);
        }
      });
      this.elements.clear.addEventListener("click", () => clearResults());
      this.elements.unsaveRun.addEventListener("click", async () => {
        const button = this.elements.unsaveRun;
        if (button.disabled) {
          return;
        }
        button.disabled = true;
        try {
          await AiReviewUtils.runUnsaveFromPickedFile();
        } catch (error) {
          setError(`取消儲存失敗: ${error instanceof Error ? error.message : String(error)}`);
        } finally {
          button.disabled = false;
        }
      });
      this.elements.diagnoseAiKeys.addEventListener("click", () => AiReviewUtils.diagnoseAiKeys());
      this.elements.debugLog.addEventListener("click", async () => {
        try {
          await DebugLogUtils.chooseFileHandle();
          await DebugLogUtils.appendEvent("debug_log_configured", {
            fileName: state.debugLogFileName
          });
        } catch (error) {
          if (error?.name === "AbortError") {
            return;
          }
          setError(`設定 debug log 失敗: ${error instanceof Error ? error.message : String(error)}`);
        }
      });
    },

    update() {
      if (!this.elements.meta) {
        return;
      }

      const target = DateUtils.parseTargetDate(state.cutoffDate);
      const aiItemCounts = AiReviewUtils.countAiItemsByTier();
      const lines = [
        `腳本版本: ${SCRIPT_VERSION}`,
        `狀態: ${state.status}`,
        `截止日期: ${target ? target.label : "未設定"}`,
        `已收集筆數: ${state.items.length}`,
        `去重鍵數量: ${state.seenKeys.size}`,
        `已解析含日期貼文: ${state.postsWithParsedDate}`,
        `最舊已見日期: ${state.oldestSeenPublished || "未知"}`,
        `自動存檔: ${getAutoSaveStatusText()}`,
        `unsave 分類: ${state.aiLoadStatus}`,
        `分類檔案: ${state.aiResultFileName || "未指定"}`,
        `分類產生時間/後端: ${state.aiResultGeneratedAt || "未知"} / ${state.aiResultBackend || "未知"}`,
        `分類來源/摘要: ${state.aiResultSourceFile || "未知"} / ${formatAiResultSummary(state.aiResultSummary)}`,
        `待取消候選/已選取: ${aiItemCounts.reviewable}/${state.aiReviewStats.selected}`,
        `目前標亮: ${state.aiReviewStats.renderedMatched}`,
        `候選分布(建議/其他/待確認): ${aiItemCounts.highConfidence}/${aiItemCounts.lowConfidence}/${aiItemCounts.unsure}`,
        `目前畫面分布(建議/其他/待確認): ${state.aiReviewStats.highConfidence}/${state.aiReviewStats.lowConfidence}/${state.aiReviewStats.unsure}`,
        `目前畫面本地候選: ${state.aiReviewStats.localCandidate}`,
        `已排除(已處理/頁面不存在): ${state.suppressedAiKeys.size}`,
        `取消儲存 已驗證/待刷新/失敗: ${state.unsaveVerifiedKeys.size}/${state.unsaveAttemptedKeys.size}/${state.unsaveFailedKeys.size}`,
        `來源頁面: ${location.pathname}`
      ];

      const debugLines = [
        `Debug Log: ${getDebugLogStatusText()}`,
        `診斷 containers/link/time/datetime: ${state.debug.articleCount}/${state.debug.postLinkCount}/${state.debug.timeNodeCount}/${state.debug.datetimeCount}`,
        `診斷 parsed/null/errors: ${state.debug.parsedPostCount}/${state.debug.nullPostCount}/${state.debug.parseErrorCount}`,
        `診斷 emptyContent: ${state.debug.emptyContentCount}`,
        `診斷 scroll target/top/client/height: ${state.debug.scrollTarget}/${state.debug.scrollTop}/${state.debug.scrollClientHeight}/${state.debug.scrollHeight}`,
        `診斷 last new/olderSeen: ${state.debug.lastNewCount}/${state.debug.lastMatchedTarget}`,
        `診斷 newInRange/newOlder/oldOnly/pendingLoad: ${state.debug.visibleInRangeCount}/${state.debug.newOlderThanTargetCount}/${state.debug.oldOnlyRounds}/${state.debug.pendingLoadRounds}`
      ];

      if (state.debug.containerSource) {
        debugLines.push(`容器來源: ${state.debug.containerSource}`);
      }

      if (state.debug.samplePostHref) {
        debugLines.push(`樣本貼文連結: ${state.debug.samplePostHref}`);
      }
      if (state.debug.sampleTimeText) {
        debugLines.push(`樣本時間: ${state.debug.sampleTimeText}`);
      }
      if (state.debug.sampleArticleText) {
        debugLines.push(`樣本文字: ${state.debug.sampleArticleText}`);
      }
      if (state.debug.visibleSignature) {
        debugLines.push(`可見貼文簽名: ${state.debug.visibleSignature}`);
      }
      if (state.debug.lastNullReason) {
        debugLines.push(`最後一筆 null 原因: ${state.debug.lastNullReason}`);
      }
      if (state.debug.oldestPostUrl) {
        debugLines.push(`最舊命中貼文: ${state.debug.oldestPostUrl}`);
      }
      if (state.debug.oldestPostPreview) {
        debugLines.push(`最舊命中文字: ${state.debug.oldestPostPreview}`);
      }
      if (state.debug.matchedTargetPostUrl) {
        debugLines.push(`觸發停止貼文: ${state.debug.matchedTargetPostUrl}`);
      }
      if (state.debug.matchedTargetPostTime) {
        debugLines.push(`觸發停止時間: ${state.debug.matchedTargetPostTime}`);
      }
      if (state.debug.matchedTargetPostPreview) {
        debugLines.push(`觸發停止文字: ${state.debug.matchedTargetPostPreview}`);
      }
      if (state.debug.emptyContentExamples?.length) {
        for (const example of state.debug.emptyContentExamples) {
          debugLines.push(`空內容樣本: ${example.authorHandle} ${example.postUrl} ${example.publishedTime}`);
          if (example.articlePreview) {
            debugLines.push(`空內容預覽: ${example.articlePreview}`);
          }
        }
      }
      if (state.autoSaveLastResult) {
        lines.push(`自動存檔結果: ${state.autoSaveLastResult}`);
      }
      if (state.debugLogLastResult) {
        debugLines.push(`Debug Log 結果: ${state.debugLogLastResult}`);
      }

      if (!isLikelySavedPage()) {
        lines.push("提醒: 目前看起來不一定是收藏頁，請確認已打開 Saved posts。");
      }

      this.elements.meta.textContent = lines.join("\n");
      if (this.elements.debugMeta) {
        this.elements.debugMeta.textContent = debugLines.join("\n");
      }
      this.elements.error.textContent = state.lastError || "";
      this.elements.start.disabled = state.isRunning;
      this.elements.stop.disabled = !state.isRunning;
      this.elements.diagnoseAiKeys.disabled = state.aiItems.length === 0;
    }
  };

  const Scroller = {
    getScrollContainer() {
      const postContainers = Parser.getArticleNodes();
      const seedNode = postContainers[0] || document.querySelector('a[href*="/post/"], a[href*="/t/"]');
      const fallback = document.scrollingElement || document.documentElement || document.body;

      for (let element = seedNode?.parentElement; element && element !== document.body; element = element.parentElement) {
        const style = window.getComputedStyle(element);
        const overflowY = style.overflowY || "";
        const isScrollable = /(auto|scroll|overlay)/i.test(overflowY) && element.scrollHeight > element.clientHeight + 40;
        if (isScrollable) {
          return element;
        }
      }

      return fallback;
    },

    getScrollMetrics(container = this.getScrollContainer()) {
      if (!container) {
        return {
          target: "unknown",
          top: 0,
          height: 0,
          client: 0
        };
      }

      if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
        const scrollingElement = document.scrollingElement || document.documentElement || document.body;
        return {
          target: "document",
          top: scrollingElement.scrollTop,
          height: scrollingElement.scrollHeight,
          client: scrollingElement.clientHeight
        };
      }

      return {
        target: `${container.tagName.toLowerCase()}${container.id ? `#${container.id}` : ""}`,
        top: container.scrollTop,
        height: container.scrollHeight,
        client: container.clientHeight
      };
    },

    scrollToEnd(container = this.getScrollContainer()) {
      if (!container) {
        return;
      }

      if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
        const scrollingElement = document.scrollingElement || document.documentElement || document.body;
        scrollingElement.scrollTop = scrollingElement.scrollHeight;
        window.scrollTo({ top: scrollingElement.scrollHeight, behavior: "auto" });
        return;
      }

      container.scrollTop = container.scrollHeight;
    },

    scrollToStart(container = this.getScrollContainer()) {
      if (!container) {
        return;
      }

      if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
        const scrollingElement = document.scrollingElement || document.documentElement || document.body;
        scrollingElement.scrollTop = 0;
        window.scrollTo({ top: 0, behavior: "auto" });
        return;
      }

      container.scrollTop = 0;
    },

    scrollByStep(container = this.getScrollContainer()) {
      if (!container) {
        return 0;
      }

      const metrics = this.getScrollMetrics(container);
      const step = Math.max(Math.floor(metrics.client * 0.85), 420);
      const nextTop = Math.min(metrics.top + step, Math.max(0, metrics.height - metrics.client));

      if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
        const scrollingElement = document.scrollingElement || document.documentElement || document.body;
        scrollingElement.scrollTop = nextTop;
        window.scrollTo({ top: nextTop, behavior: "auto" });
        return nextTop;
      }

      container.scrollTop = nextTop;
      return nextTop;
    },

    isNearBottom(metrics, threshold = 24) {
      if (!metrics) {
        return false;
      }
      return metrics.top + metrics.client >= Math.max(0, metrics.height - threshold);
    },

    nudgeNearBottom(container = this.getScrollContainer(), metrics = this.getScrollMetrics(container)) {
      if (!container || !metrics) {
        return 0;
      }

      const retreatDistance = Math.max(
        Math.min(SCROLL_BOTTOM_NUDGE_PX, Math.floor(metrics.client * 0.35)),
        120
      );
      const retreatTop = Math.max(0, metrics.top - retreatDistance);

      if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
        const scrollingElement = document.scrollingElement || document.documentElement || document.body;
        scrollingElement.scrollTop = retreatTop;
        window.scrollTo({ top: retreatTop, behavior: "auto" });
        return retreatTop;
      }

      container.scrollTop = retreatTop;
      return retreatTop;
    },

    collectVisibleSignature(limit = 12) {
      const keys = [];
      for (const article of Parser.getArticleNodes()) {
        if (!AiReviewUtils.isElementVisible(article)) {
          continue;
        }
        const post = Parser.parseArticle(article);
        const key = post?.postId || post?.postUrl || "";
        if (!key) {
          continue;
        }
        keys.push(key);
        if (keys.length >= limit) {
          break;
        }
      }
      return keys.join("|");
    },

    async start() {
      if (state.isRunning) {
        return;
      }

      const target = DateUtils.parseTargetDate(state.cutoffDate);
      if (!target) {
        setError("請先輸入有效的截止日期，格式需為 YYYY-MM-DD。");
        return;
      }

      setError("");
      state.isRunning = true;
      state.status = "抓取中";
      state.postsWithParsedDate = 0;
      state.oldestSeenPublished = state.oldestSeenPublished || "";

      if (!state.onlyNew) {
        state.lastRunNewCount = 0;
      }

      UI.update();

      let oldOnlyRounds = 0;
      let pendingLoadRounds = 0;

      while (state.isRunning) {
        const scrollContainer = this.getScrollContainer();
        const { newCount, oldestPublished, sawOlderThanTarget, newOlderThanTargetCount, newInRangeCount, visibleSignature } = processVisiblePosts(target);
        const currentMetrics = this.getScrollMetrics(scrollContainer);
        state.debug.scrollTarget = currentMetrics.target;
        state.debug.scrollTop = currentMetrics.top;
        state.debug.scrollHeight = currentMetrics.height;
        state.debug.scrollClientHeight = currentMetrics.client;
        state.debug.lastNewCount = newCount;
        state.debug.lastMatchedTarget = sawOlderThanTarget ? "yes" : "no";
        state.debug.visibleInRangeCount = newInRangeCount;
        state.debug.newOlderThanTargetCount = newOlderThanTargetCount;
        state.debug.oldOnlyRounds = oldOnlyRounds;
        state.debug.pendingLoadRounds = pendingLoadRounds;
        state.debug.visibleSignature = visibleSignature.slice(0, 180);

        if (oldestPublished) {
          state.oldestSeenPublished = oldestPublished;
        }

        if (state.maxItems > 0 && state.items.length >= state.maxItems) {
          this.stop(`完成: 已達最大抓取筆數 ${state.maxItems}`);
          break;
        }

        if (newOlderThanTargetCount > 0 && newInRangeCount === 0) {
          oldOnlyRounds += 1;
        } else {
          oldOnlyRounds = 0;
        }
        state.debug.oldOnlyRounds = oldOnlyRounds;

        if (oldOnlyRounds >= DEFAULT_MAX_OLD_ONLY_ROUNDS) {
          this.stop("完成: 連續數輪只看到早於最早日期的貼文");
          break;
        }

        if (newCount === 0 && this.isNearBottom(currentMetrics)) {
          this.nudgeNearBottom(scrollContainer, currentMetrics);
          await wait(Math.min(state.scrollDelay, SCROLL_BOTTOM_NUDGE_DELAY));
        }

        this.scrollToEnd(scrollContainer);
        UI.update();
        saveState();
        await wait(state.scrollDelay);

        const settledContainer = this.getScrollContainer();
        const settledMetrics = this.getScrollMetrics(settledContainer);
        const settledSignature = this.collectVisibleSignature();
        const scrollAdvanced = settledMetrics.top > currentMetrics.top || settledMetrics.height > currentMetrics.height;
        const viewportChanged = settledSignature !== visibleSignature;

        if (newCount === 0 && !scrollAdvanced && !viewportChanged) {
          pendingLoadRounds += 1;
        } else {
          pendingLoadRounds = 0;
        }

        state.debug.pendingLoadRounds = pendingLoadRounds;
        state.debug.visibleSignature = settledSignature.slice(0, 180);

        if (pendingLoadRounds >= DEFAULT_MAX_PENDING_LOAD_ROUNDS) {
          this.stop("完成: 連續數次未載入新內容，可能已到底部");
          break;
        }
      }
    },

    stop(statusText) {
      state.isRunning = false;
      state.status = statusText || "已停止";
      saveState();
      UI.update();
      if (state.items.length > 0) {
        AutoSaveUtils.saveItems(getExportableItems()).catch((error) => {
          state.autoSaveLastResult = `自動存檔失敗: ${error instanceof Error ? error.message : String(error)}`;
          UI.update();
          setError(`自動存檔失敗: ${error instanceof Error ? error.message : String(error)}`);
        });
      }
    }
  };

  function createState() {
    const stored = readStoredState();
    const items = Array.isArray(stored.items) ? stored.items : [];
    const seenKeys = new Set(items.map((item) => item.postId || item.postUrl).filter(Boolean));
    const datedKeys = new Set(
      items
        .filter((item) => Number.isFinite(item.publishedEpochMs))
        .map((item) => item.postId || item.postUrl)
        .filter(Boolean)
    );
    return {
      items,
      seenKeys,
      datedKeys,
      isRunning: false,
      status: "待機中",
      cutoffDate: stored.cutoffDate || "",
      scrollDelay: stored.scrollDelay || DEFAULT_SCROLL_DELAY,
      maxItems: stored.maxItems || DEFAULT_MAX_ITEMS,
      onlyNew: Boolean(stored.onlyNew),
      lastError: "",
      postsWithParsedDate: datedKeys.size,
      oldestSeenPublished: stored.oldestSeenPublished || "",
      lastRunNewCount: 0,
      autoSaveReady: false,
      autoSaveFileName: "",
      autoSaveLastResult: "",
      debugLogReady: false,
      debugLogFileName: "",
      debugLogLastResult: "",
      aiItems: [],
      aiMap: Object.create(null),
      aiIndexMap: new Map(),
      aiLoadStatus: "未載入 unsave 分類",
      aiResultFileName: "",
      aiResultGeneratedAt: "",
      aiResultBackend: "",
      aiResultSourceFile: "",
      aiResultSummary: null,
      aiHighlightsActive: false,
      selectedAiKeys: new Set(),
      highlightedKeys: new Set(),
      suppressedAiKeys: new Set(Array.isArray(stored.suppressedAiKeys) ? stored.suppressedAiKeys.filter(Boolean) : []),
      unsaveAttemptedKeys: new Set(),
      unsaveVerifiedKeys: new Set(),
      unsaveFailedKeys: new Set(),
      aiReviewStats: createAiReviewStats(),
      debug: {
        articleCount: 0,
        containerSource: "",
        postLinkCount: 0,
        timeNodeCount: 0,
        datetimeCount: 0,
        parsedPostCount: 0,
        nullPostCount: 0,
        parseErrorCount: 0,
        emptyContentCount: 0,
        emptyContentExamples: [],
        samplePostHref: "",
        sampleTimeText: "",
        sampleArticleText: "",
        lastNullReason: "",
        scrollTarget: "",
        scrollTop: 0,
        scrollHeight: 0,
        scrollClientHeight: 0,
        lastNewCount: 0,
        lastMatchedTarget: "no",
        visibleInRangeCount: 0,
        newOlderThanTargetCount: 0,
        oldOnlyRounds: 0,
        pendingLoadRounds: 0,
        visibleSignature: "",
        oldestPostUrl: "",
        oldestPostPreview: "",
        matchedTargetPostUrl: "",
        matchedTargetPostTime: "",
        matchedTargetPostPreview: ""
      }
    };
  }

  function readStoredState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (_error) {
      return {};
    }
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        items: state.items,
        cutoffDate: state.cutoffDate,
        scrollDelay: state.scrollDelay,
        maxItems: state.maxItems,
        onlyNew: state.onlyNew,
        oldestSeenPublished: state.oldestSeenPublished,
        suppressedAiKeys: Array.from(state.suppressedAiKeys)
      }));
    } catch (_error) {
      // Ignore storage issues and keep the collector usable.
    }
  }

  function createAiReviewStats() {
    return {
      renderedMatched: 0,
      selected: 0,
      reviewable: 0,
      highConfidence: 0,
      lowConfidence: 0,
      unsure: 0,
      localCandidate: 0
    };
  }

  function formatAiResultSummary(summary) {
    if (!summary || typeof summary !== "object") {
      return "未知";
    }
    const total = summary.total ?? "?";
    const unsave = summary.unsave ?? summary.ai ?? "?";
    const keep = summary.keep ?? summary.not_ai ?? "?";
    const unsure = summary.unsure ?? "?";
    const failed = summary.failed ?? "?";
    return `total ${total}, 取消 ${unsave}, 保留 ${keep}, 待判斷 ${unsure}, failed ${failed}`;
  }

  function getExportableItems() {
    return state.items.map(({ publishedEpochMs, ...item }) => item);
  }

  function getAutoSaveStatusText() {
    if (state.autoSaveReady) {
      return `已設定 (${state.autoSaveFileName || "catch.json"})`;
    }
    if (state.autoSaveFileName) {
      return `已設定但需重授權 (${state.autoSaveFileName})`;
    }
    return "未設定";
  }

  function getDebugLogStatusText() {
    if (state.debugLogReady) {
      return `已設定 (${state.debugLogFileName || "threads-unsave-debug.ndjson"})`;
    }
    if (state.debugLogFileName) {
      return `已設定但需重授權 (${state.debugLogFileName})`;
    }
    return "未設定";
  }

  function buildPostKeySignature(posts, limit = 12) {
    return posts
      .map((post) => post?.postId || post?.postUrl || "")
      .filter(Boolean)
      .slice(0, limit)
      .join("|");
  }

  function processVisiblePosts(target) {
    const posts = Parser.collectPosts();
    let newCount = 0;
    let oldestPublished = state.oldestSeenPublished || "";
    let oldestPost = null;
    let sawOlderThanTarget = false;
    let newOlderThanTargetCount = 0;
    let newInRangeCount = 0;

    for (const post of posts) {
      const uniqueKey = post.postId || post.postUrl;
      if (!uniqueKey) {
        continue;
      }

      if (Number.isFinite(post.publishedEpochMs)) {
        if (!state.datedKeys.has(uniqueKey)) {
          state.datedKeys.add(uniqueKey);
          state.postsWithParsedDate += 1;
        }
        if (!oldestPublished || post.publishedTime < oldestPublished) {
          oldestPublished = post.publishedTime;
          oldestPost = post;
        }
        if (DateUtils.isOlderThanTargetRange(post.publishedEpochMs, target)) {
          sawOlderThanTarget = true;
        }
      }

      if (state.seenKeys.has(uniqueKey)) {
        continue;
      }

      if (Number.isFinite(post.publishedEpochMs)) {
        if (DateUtils.isOlderThanTargetRange(post.publishedEpochMs, target)) {
          newOlderThanTargetCount += 1;
          continue;
        }
        if (DateUtils.isWithinTargetRange(post.publishedEpochMs, target)) {
          newInRangeCount += 1;
        }
      }

      state.seenKeys.add(uniqueKey);
      state.items.push(post);
      state.lastRunNewCount += 1;
      newCount += 1;
    }

    if (oldestPost) {
      state.debug.oldestPostUrl = oldestPost.postUrl || "";
      state.debug.oldestPostPreview = (oldestPost.contentText || "").slice(0, 120);
    }
    state.debug.matchedTargetPostUrl = "";
    state.debug.matchedTargetPostTime = "";
    state.debug.matchedTargetPostPreview = "";

    return {
      newCount,
      oldestPublished,
      sawOlderThanTarget,
      newOlderThanTargetCount,
      newInRangeCount,
      visibleSignature: buildPostKeySignature(posts)
    };
  }

  function clearResults() {
    AiReviewUtils.clearHighlights();
    state.items = [];
    state.seenKeys = new Set();
    state.datedKeys = new Set();
    state.postsWithParsedDate = 0;
    state.oldestSeenPublished = "";
    state.lastRunNewCount = 0;
    state.aiItems = [];
    state.aiMap = Object.create(null);
    state.aiIndexMap = new Map();
    state.aiLoadStatus = "未載入 unsave 分類";
    state.aiResultFileName = "";
    state.aiResultGeneratedAt = "";
    state.aiResultBackend = "";
    state.aiResultSourceFile = "";
    state.aiResultSummary = null;
    state.aiHighlightsActive = false;
    state.highlightedKeys = new Set();
    state.suppressedAiKeys = new Set();
    state.unsaveAttemptedKeys = new Set();
    state.unsaveVerifiedKeys = new Set();
    state.unsaveFailedKeys = new Set();
    state.aiReviewStats = createAiReviewStats();
    state.status = "待機中";
    state.lastError = "";
    saveState();
    UI.update();
  }

  function setStatus(message) {
    state.status = message;
    UI.update();
  }

  function setError(message) {
    state.lastError = message;
    UI.update();
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function isLikelySavedPage() {
    const path = location.pathname.toLowerCase();
    if (path.includes("saved")) {
      return true;
    }
    const pageText = document.body?.innerText?.slice(0, 2000) || "";
    return /saved/i.test(pageText);
  }

  function boot() {
    UI.init();
    AutoSaveUtils.refreshStatus().catch(() => {
      state.autoSaveReady = false;
      state.autoSaveFileName = "";
      UI.update();
    });
    DebugLogUtils.refreshStatus().catch(() => {
      state.debugLogReady = false;
      state.debugLogFileName = "";
      UI.update();
    });
    const observer = new MutationObserver(() => {
      if (!document.getElementById(PANEL_ID)) {
        UI.init();
      }
      AiReviewUtils.scheduleSync();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener("scroll", () => AiReviewUtils.scheduleSync(), true);
    window.setInterval(() => AiReviewUtils.scheduleSync(), 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
