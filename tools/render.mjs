#!/usr/bin/env node
// Draw a converted character in headless Chromium and write a contact sheet of poses, so a conversion
// can be checked without a screen.
//   node tools/render.mjs my-characters/out/mina            (a folder or a .livliv)
//   node tools/render.mjs --all
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { basename, dirname, extname, join, normalize, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const OUT = join(ROOT, 'my-characters', 'out')
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
  '.webp': 'image/webp', '.png': 'image/png', '.livliv': 'application/vnd.livliv.model+zip', '.css': 'text/css' }

const POSES = [
  ['rest', {}],
  ['turn left', { angleX: -24, bodyX: -5 }],
  ['turn right', { angleX: 24, bodyX: 5 }],
  ['look up', { angleY: -16 }],
  ['look down', { angleY: 16 }],
  ['tilt', { angleZ: 20 }],
  ['eyes closed', { eyeLOpen: 0, eyeROpen: 0 }],
  ['gaze aside', { eyeBallX: 1, eyeBallY: -0.4 }],
  ['mouth half', { mouthOpen: 0.45 }],
  ['mouth open', { mouthOpen: 1 }],
  ['mouth round', { mouthOpen: 0.9, vowel: -1 }],
  ['mouth wide', { mouthOpen: 0.9, vowel: 1 }],
]
const REST = { angleX: 0, angleY: 0, angleZ: 0, eyeLOpen: 1, eyeROpen: 1, eyeBallX: 0, eyeBallY: 0,
  mouthOpen: 0, vowel: 0, smile: 0, bodyX: 0, bodyZ: 0, breath: 0 }

if (!existsSync(join(ROOT, 'dist/index.js'))) {
  console.error('render: build the player first (npm run build)'); process.exit(1)
}

const server = createServer((req, res) => {
  const p = join(ROOT, normalize(decodeURIComponent(req.url.split('?')[0])).replace(/^(\.\.[/\\])+/, ''))
  if (!existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404).end(); return }
  res.writeHead(200, { 'content-type': TYPES[extname(p)] || 'application/octet-stream' })
  res.end(readFileSync(p))
})
await new Promise((r) => server.listen(0, '127.0.0.1', r))
const base = `http://127.0.0.1:${server.address().port}`

let targets = process.argv.slice(2).filter((a) => a !== '--all')
if (!targets.length) {
  targets = existsSync(OUT) ? readdirSync(OUT).map((d) => join(OUT, d))
    .filter((p) => statSync(p).isDirectory() && existsSync(join(p, 'model.json'))) : []
}
if (!targets.length) { console.error('render: nothing to draw in my-characters/out/'); server.close(); process.exit(1) }

const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium',
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--no-sandbox', '--headless'],
})
let bad = 0
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 })
  page.on('console', (m) => { if (m.type() === 'error') console.log('   [page]', m.text()) })
  await page.goto(`${base}/tools/render.html`)
  if (!await page.evaluate(async () => (await import('/dist/index.js')).Player.isSupported())) {
    console.error('render: this browser has no WebGL2'); process.exit(1)
  }
  for (const t of targets) {
    const dir = resolve(t)
    const id = basename(dir).replace(/\.livliv$/, '')
    const url = `${base}/${relative(ROOT, dir).split('\\').join('/')}${statSync(dir).isDirectory() ? '/' : ''}`
    process.stdout.write(`· ${id}: `)
    const info = await page.evaluate((u) => window.open_(u), url)
    const shots = []
    for (const [name, p] of POSES) shots.push([name, await page.evaluate((a) => window.pose(a[0]), [{ ...REST, ...p }])])
    const errs = await page.evaluate(() => window.errors.splice(0))
    const isDir = statSync(dir).isDirectory()
    const dst = isDir ? join(dir, '_poses') : join(dirname(dir), `${id}_poses`)
    mkdirSync(dst, { recursive: true })
    for (const [name, data] of shots) {
      writeFileSync(join(dst, name.replace(/ /g, '_') + '.png'), Buffer.from(data.split(',')[1], 'base64'))
    }
    const sizes = shots.map(([, d]) => Buffer.from(d.split(',')[1], 'base64').length)
    const same = new Set(shots.map(([, d]) => d)).size
    console.log(`${info.name || id}: ${shots.length} poses, ${same} different; ${errs.length ? 'ERRORS: ' + errs.join('; ') : 'no page errors'}`)
    if (errs.length || same < 6) bad++
    if (same < 6) console.log('   ! the poses barely differ: the rig may not be moving')
    void sizes
  }
} finally {
  await browser.close(); server.close()
}
process.exit(bad ? 1 : 0)
