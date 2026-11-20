// 오프라인에서도 마지막으로 본 목록을 열 수 있게 하는 서비스 워커
const CACHE = "etnews-v1";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./icon-180.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // 기사 데이터와 페이지는 네트워크 우선, 실패하면 저장본
  if (url.pathname.endsWith("articles.json") || e.request.mode === "navigate") {
    const key = url.pathname.endsWith("articles.json") ? "./articles.json" : "./index.html";
    e.respondWith(
      fetch(e.request)
        .then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(key, copy)); return r; })
        .catch(() => caches.match(key))
    );
    return;
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
