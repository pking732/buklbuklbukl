#!/usr/bin/env python3
"""
Идемпотентный патч VPS-агента: добавляет эндпоинт POST /vps/keys/traffic.
Считает per-user трафик из xray statsquery по counter'у user>>><deviceKeyId>>>>traffic>>>{uplink,downlink}.
Защищён существующим app.use("/vps", ...) Bearer-мидлвари.
"""
import sys

PATH = "/opt/vps-agent/src/index.js"

ROUTE = r'''
// ── Traffic (per-user из xray stats) ──────────────────────────────────────────
app.post("/vps/keys/traffic", (req, res) => {
  const { deviceKeyId, reset } = req.body;
  if (!deviceKeyId) return res.status(400).json({ error: "deviceKeyId required" });
  // Защита от инъекции в shell: только безопасные символы.
  if (!/^[A-Za-z0-9_\-]+$/.test(deviceKeyId)) {
    return res.status(400).json({ error: "invalid deviceKeyId" });
  }
  let uplink = 0, downlink = 0;
  try {
    const resetFlag = reset ? "-reset" : "";
    const out = execSync(
      `xray api statsquery --server=127.0.0.1:10085 -pattern "user>>>${deviceKeyId}>>>traffic>>>" ${resetFlag}`,
      { encoding: "utf8", timeout: 8000 }
    );
    const data = JSON.parse(out);
    for (const s of (data.stat || [])) {
      if (s.name.endsWith(">>>uplink")) uplink = parseInt(s.value || "0", 10);
      else if (s.name.endsWith(">>>downlink")) downlink = parseInt(s.value || "0", 10);
    }
  } catch (e) {
    // Счётчика нет (юзер не подключался) или ошибка — возвращаем нули.
  }
  res.json({ uplink, downlink });
});

'''

src = open(PATH, encoding="utf-8").read()
if "/vps/keys/traffic" in src:
    print("ALREADY_PATCHED")
    sys.exit(0)

anchor = "const PORT ="
idx = src.find(anchor)
if idx == -1:
    print("ANCHOR_NOT_FOUND")
    sys.exit(1)

src = src[:idx] + ROUTE + src[idx:]
open(PATH, "w", encoding="utf-8").write(src)
print("PATCHED")
