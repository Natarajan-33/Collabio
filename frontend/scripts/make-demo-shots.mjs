// Renders fictional "Post analytics" screenshots for the demo (no real platform UI or
// logos) into public/demo/. Run: node scripts/make-demo-shots.mjs
import { chromium } from "@playwright/test"
import { mkdirSync } from "node:fs"

const SHOTS = [
  { file: "analytics-312k.png", views: "312,000", likes: "18.4K", shares: "1,206", watch: "41%" },
  { file: "analytics-812k.png", views: "812,400", likes: "52.9K", shares: "4,388", watch: "47%" },
  { file: "analytics-1240k.png", views: "1,240,000", likes: "97.1K", shares: "9,012", watch: "52%" },
]

const html = (s) => `<!doctype html><html><head><style>
  body{margin:0;font-family:Inter,Segoe UI,system-ui,sans-serif;background:#0f1115;color:#e9eaee}
  .card{width:720px;height:520px;box-sizing:border-box;padding:40px;background:linear-gradient(160deg,#171a21,#0f1115)}
  .top{display:flex;justify-content:space-between;align-items:center;color:#9aa0ab;font-size:18px}
  .pill{border:1px solid #2b2f39;border-radius:999px;padding:6px 14px;font-size:15px}
  h1{font-size:22px;font-weight:600;margin:28px 0 6px;color:#e9eaee}
  .sub{color:#9aa0ab;font-size:16px}
  .views{font-size:84px;font-weight:700;letter-spacing:-2px;margin:26px 0 4px}
  .label{color:#9aa0ab;font-size:18px}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:36px}
  .stat{background:#1b1f27;border:1px solid #252a34;border-radius:14px;padding:18px}
  .stat b{display:block;font-size:30px;margin-top:6px}
  .stat span{color:#9aa0ab;font-size:15px}
  .bar{height:8px;border-radius:8px;background:#252a34;margin-top:34px;overflow:hidden}
  .bar i{display:block;height:100%;width:${s.watch};background:#ff7a45}
</style></head><body><div class="card">
  <div class="top"><span>Post analytics</span><span class="pill">Last 14 days</span></div>
  <h1>Two weeks with Lumen Pods</h1><div class="sub">Short video · @priyareviews · posted Nov 2</div>
  <div class="views">${s.views}</div><div class="label">Views</div>
  <div class="grid">
    <div class="stat"><span>Likes</span><b>${s.likes}</b></div>
    <div class="stat"><span>Shares</span><b>${s.shares}</b></div>
    <div class="stat"><span>Avg. watched</span><b>${s.watch}</b></div>
  </div>
  <div class="bar"><i></i></div>
</div></body></html>`

mkdirSync("public/demo", { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 720, height: 520 } })
for (const shot of SHOTS) {
  await page.setContent(html(shot))
  await page.screenshot({ path: `public/demo/${shot.file}` })
  console.log("wrote", shot.file)
}
await browser.close()
