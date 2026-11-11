#!/usr/bin/env node
// A local server for the converter's own pages: serves the repository, saves a marks file the
// marker edits, and runs the converter again when the marker asks. Local only.
//   node tools/serve.mjs [port]    ->  http://127.0.0.1:8080/tools/mark.html
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findPython } from './py.mjs'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const PORT = Number(process.argv[2] || 8080)
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.json': 'application/json', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.css': 'text/css', '.livliv': 'application/vnd.livliv.model+zip', '.svg': 'image/svg+xml' }

const json = (res, code, body) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)) }
const body = (req) => new Promise((done, fail) => {
  let n = 0; const parts = []
  req.on('data', (c) => { n += c.length; if (n > 4e6) { req.destroy(); fail(new Error('too big')) } else parts.push(c) })
  req.on('end', () => done(Buffer.concat(parts).toString('utf8')))
  req.on('error', fail)
})
const safeId = (id) => /^[A-Za-z0-9_-]{1,64}$/.test(id)

const server = createServer(async (req, res) => {
  const u = new URL(req.url, 'http://127.0.0.1')
  try {
    // the characters this workspace holds, newest first
    if (u.pathname === '/api/characters') {
      const dir = join(ROOT, 'my-characters', 'out')
      const ids = existsSync(dir) ? readdirSync(dir).filter((d) => existsSync(join(dir, d, 'model.json'))) : []
      return json(res, 200, ids.sort().map((id) => {
        const m = JSON.parse(readFileSync(join(dir, id, 'model.json'), 'utf8'))
        return { id, name: m.name, canvas: m.canvas, layers: m.layers.length,
          marks: existsSync(join(ROOT, 'my-characters', 'marks', `${id}.json`)) }
      }))
    }
    if (u.pathname === '/api/marks' && req.method === 'PUT') {
      const id = u.searchParams.get('id') || ''
      if (!safeId(id)) return json(res, 400, { error: 'bad id' })
      const text = await body(req)
      const marks = JSON.parse(text)                      // reject anything that is not JSON
      if (!marks.canvas || !marks.head) return json(res, 400, { error: 'not a marks file' })
      const dir = join(ROOT, 'my-characters', 'marks')
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, `${id}.json`), JSON.stringify(marks, null, 1))
      return json(res, 200, { saved: `my-characters/marks/${id}.json` })
    }
    if (u.pathname === '/api/convert' && req.method === 'POST') {
      const id = u.searchParams.get('id') || ''
      if (!safeId(id)) return json(res, 400, { error: 'bad id' })
      const src = readdirSync(join(ROOT, 'my-characters', 'source'))
        .find((f) => f.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') === id)
      if (!src) return json(res, 404, { error: `no picture in my-characters/source/ for ${id}` })
      const py = findPython()
      if (!py) return json(res, 500, { error: 'no Python 3 on this machine' })
      const p = spawn(py[0], [...py[1], '-I', join(ROOT, 'tools', 'convert.py'),
        join(ROOT, 'my-characters', 'source', src)], { cwd: ROOT, shell: process.platform === 'win32' })
      let out = ''
      p.stdout.on('data', (d) => { out += d }); p.stderr.on('data', (d) => { out += d })
      return p.on('close', (code) => json(res, code ? 500 : 200, { code, log: out }))
    }

    const path = join(ROOT, normalize(decodeURIComponent(u.pathname)).replace(/^(\.\.[/\\])+/, ''))
    if (!resolve(path).startsWith(resolve(ROOT))) return json(res, 403, { error: 'outside' })
    if (!existsSync(path) || statSync(path).isDirectory()) { res.writeHead(404).end('not found'); return }
    res.writeHead(200, { 'content-type': TYPES[extname(path)] || 'application/octet-stream', 'cache-control': 'no-store' })
    res.end(readFileSync(path))
  } catch (e) {
    json(res, 500, { error: String(e && e.message || e) })
  }
})
server.listen(PORT, '127.0.0.1', () => {
  console.log(`marker : http://127.0.0.1:${PORT}/tools/mark.html`)
  console.log(`preview: http://127.0.0.1:${PORT}/tools/preview.html`)
})
