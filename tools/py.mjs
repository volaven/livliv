#!/usr/bin/env node
// Run one of the converter's Python tools with whatever Python this machine calls it by:
// `python3` on macOS and Linux, `py -3` or `python` on Windows. Checks the three packages the
// tools need and says how to install them before a script fails halfway.
//   node tools/py.mjs convert.py --all
import { spawn, spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const TRY = process.platform === 'win32'
  ? [['py', ['-3']], ['python', []], ['python3', []]]
  : [['python3', []], ['python', []]]

export function findPython() {
  for (const [cmd, pre] of TRY) {
    const r = spawnSync(cmd, [...pre, '-c', 'import sys; print(sys.version_info[0])'],
      { encoding: 'utf8', shell: process.platform === 'win32' })
    if (r.status === 0 && Number(String(r.stdout).trim()) >= 3) return [cmd, pre]
  }
  return null
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const found = findPython()
  if (!found) {
    console.error('No Python 3 found. Install it from https://www.python.org/downloads/ (on Windows tick'
      + ' "Add python.exe to PATH"), then run this again.')
    process.exit(127)
  }
  const [cmd, pre] = found

  const deps = spawnSync(cmd, [...pre, '-c', 'import numpy, PIL, jsonschema'],
    { encoding: 'utf8', shell: process.platform === 'win32' })
  if (deps.status !== 0) {
    const how = process.platform === 'win32' ? `${cmd} ${pre.join(' ')} -m pip` : `${cmd} -m pip`
    console.error('The converter needs three Python packages. Install them with:\n'
      + `  ${how} install -r tools/requirements.txt\n`)
    process.exit(1)
  }

  const [script, ...rest] = process.argv.slice(2)
  if (!script) {
    console.error('usage: node tools/py.mjs <script.py> [arguments]')
    process.exit(2)
  }
  const child = spawn(cmd, [...pre, '-I', join(ROOT, 'tools', script), ...rest],
    { stdio: 'inherit', cwd: ROOT, shell: process.platform === 'win32' })
  child.on('close', (code) => process.exit(code ?? 0))
}
