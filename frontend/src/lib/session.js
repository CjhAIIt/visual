import { AUTH_STORAGE_KEY } from "@/appConfig";
import { requestApi } from "./api";

const SECURE_SESSION_VERSION = 1;
const SECURE_STORE_DB = "plantops-secure-store";
const SECURE_STORE_NAME = "secrets";
const SECURE_TOKEN_KEY = "auth-token-key";
const textEncoder = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
const textDecoder = typeof TextDecoder !== "undefined" ? new TextDecoder() : null;

function canUseSecureSessionStorage() {
  return typeof window !== "undefined"
    && Boolean(window.crypto?.subtle)
    && typeof window.indexedDB !== "undefined"
    && Boolean(textEncoder)
    && Boolean(textDecoder);
}

function toBase64(bytes) {
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary);
}

function fromBase64(value) {
  const binary = window.atob(value);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function openSecureStore() {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(SECURE_STORE_DB, 1);
    request.onerror = () => reject(request.error || new Error("无法打开安全存储"));
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(SECURE_STORE_NAME)) {
        database.createObjectStore(SECURE_STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

async function readSecureValue(key) {
  const database = await openSecureStore();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(SECURE_STORE_NAME, "readonly");
    const store = transaction.objectStore(SECURE_STORE_NAME);
    const request = store.get(key);
    request.onerror = () => reject(request.error || new Error("读取安全存储失败"));
    request.onsuccess = () => resolve(request.result || null);
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => reject(transaction.error || new Error("读取安全存储失败"));
  });
}

async function writeSecureValue(key, value) {
  const database = await openSecureStore();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(SECURE_STORE_NAME, "readwrite");
    const store = transaction.objectStore(SECURE_STORE_NAME);
    const request = store.put(value, key);
    request.onerror = () => reject(request.error || new Error("写入安全存储失败"));
    transaction.oncomplete = () => {
      database.close();
      resolve(value);
    };
    transaction.onerror = () => reject(transaction.error || new Error("写入安全存储失败"));
  });
}

async function getOrCreateSecureTokenKey() {
  const existing = await readSecureValue(SECURE_TOKEN_KEY);
  if (existing) {
    return existing;
  }

  const nextKey = await window.crypto.subtle.generateKey(
    {
      name: "AES-GCM",
      length: 256,
    },
    false,
    ["encrypt", "decrypt"],
  );
  await writeSecureValue(SECURE_TOKEN_KEY, nextKey);
  return nextKey;
}

function parseEncryptedEnvelope(rawValue) {
  if (!rawValue) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawValue);
    if (
      parsed?.v === SECURE_SESSION_VERSION
      && typeof parsed.iv === "string"
      && typeof parsed.cipher === "string"
    ) {
      return parsed;
    }
  } catch {
    return null;
  }

  return null;
}

async function encryptToken(token) {
  if (!token) {
    return "";
  }
  if (!canUseSecureSessionStorage()) {
    return token;
  }

  const key = await getOrCreateSecureTokenKey();
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await window.crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    textEncoder.encode(token),
  );

  return JSON.stringify({
    v: SECURE_SESSION_VERSION,
    iv: toBase64(iv),
    cipher: toBase64(new Uint8Array(ciphertext)),
  });
}

async function decryptToken(rawValue) {
  if (!rawValue) {
    return "";
  }

  const envelope = parseEncryptedEnvelope(rawValue);
  if (!envelope) {
    return rawValue;
  }
  if (!canUseSecureSessionStorage()) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return "";
  }

  try {
    const key = await getOrCreateSecureTokenKey();
    const plaintext = await window.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromBase64(envelope.iv) },
      key,
      fromBase64(envelope.cipher),
    );
    return textDecoder.decode(plaintext);
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return "";
  }
}

export async function readStoredToken() {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const rawValue = window.localStorage.getItem(AUTH_STORAGE_KEY) || "";
    return await decryptToken(rawValue);
  } catch {
    return window.localStorage.getItem(AUTH_STORAGE_KEY) || "";
  }
}

export async function writeStoredToken(token) {
  if (typeof window === "undefined") {
    return;
  }
  if (!token) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return;
  }

  try {
    const encryptedValue = await encryptToken(token);
    window.localStorage.setItem(AUTH_STORAGE_KEY, encryptedValue);
  } catch {
    window.localStorage.setItem(AUTH_STORAGE_KEY, token);
  }
}

export async function fetchSession(token, signal) {
  return requestApi("/auth/session", { token, signal });
}

export async function loginRequest(payload) {
  return requestApi("/auth/login", { method: "POST", body: payload });
}

export async function registerRequest(payload) {
  const normalizedPayload = {
    username: payload?.username ?? "",
    password: payload?.password ?? "",
    display_name: payload?.displayName ?? payload?.display_name ?? "",
  };
  return requestApi("/auth/register", { method: "POST", body: normalizedPayload });
}

export async function logoutRequest(token) {
  return requestApi("/auth/logout", { method: "POST", token });
}
