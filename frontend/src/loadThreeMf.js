/**
 * Universal client-side 3MF color extractor.
 *
 * Three.js ThreeMFLoader uses querySelector('colorgroup'), which misses
 * namespaced nodes such as <m:colorgroup>. This loader unpacks the ZIP with
 * JSZip, walks XML by localName / getElementsByTagNameNS('*', …), and applies:
 *   A — multi-body <object>/<volume> solid colors
 *   B — material extension colorgroup + triangle pid/p1/p2/p3
 *   C — embedded 3D/Textures maps (flipY = false)
 *   D — per-vertex RGB on <vertex>
 *   E — Bambu/Orca component `path` + paint_color / extruder → filament_colour
 */

import JSZip from 'jszip'

const DISTINCT_PALETTE = [
  '#E05A4A',
  '#3DBA86',
  '#4A90E8',
  '#E8953A',
  '#9B59B6',
  '#F1C40F',
  '#1ABC9C',
  '#E84393',
]

/** Bambu/Orca paint_color bit-tree codes → 1-based filament slot. */
const PAINT_SLOT_CODES = [
  '4',
  '8',
  '0C',
  '1C',
  '2C',
  '3C',
  '4C',
  '5C',
  '6C',
  '7C',
  '8C',
  '9C',
  'AC',
  'BC',
  'CC',
  'DC',
]

const FALLBACK_BEIGE = 0xf2d4a8
const PLACEHOLDER_COLORS = new Set([0xffffff, 0xcccccc, 0x808080, 0xaaaaaa, FALLBACK_BEIGE])

function zipPath(name) {
  return String(name || '')
    .replace(/\\/g, '/')
    .replace(/^\//, '')
}

function normalizeModelPath(p) {
  return String(p || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .toLowerCase()
}

function localName(el) {
  if (!el) return ''
  const raw = el.localName || el.nodeName || ''
  return String(raw).split(':').pop().toLowerCase()
}

function allByTag(root, tag) {
  if (!root?.getElementsByTagNameNS) return []
  return Array.from(root.getElementsByTagNameNS('*', tag))
}

function kids(el, tag) {
  return Array.from(el?.children || []).filter((c) => localName(c) === tag)
}

function attr(el, name) {
  if (!el) return null
  const direct = el.getAttribute?.(name)
  if (direct != null && direct !== '') return direct
  if (!el.attributes) return null
  const needle = String(name).toLowerCase()
  for (const a of Array.from(el.attributes)) {
    const key = (a.localName || a.name || '').split(':').pop().toLowerCase()
    if (key === needle) return a.value
  }
  return null
}

export function parseHexColor(raw) {
  if (raw == null) return null
  let s = String(raw).trim()
  if (!s) return null
  if (s[0] !== '#') s = `#${s}`
  if (s.length === 4) s = `#${s[1]}${s[1]}${s[2]}${s[2]}${s[3]}${s[3]}`
  if (s.length < 7) return null
  const r = parseInt(s.slice(1, 3), 16)
  const g = parseInt(s.slice(3, 5), 16)
  const b = parseInt(s.slice(5, 7), 16)
  if ([r, g, b].some((n) => Number.isNaN(n))) return null
  return { r: r / 255, g: g / 255, b: b / 255, hex: s.slice(0, 7).toUpperCase() }
}

function rgb255(r, g, b) {
  const to1 = (v) => {
    const n = Number(v)
    if (!Number.isFinite(n)) return null
    return n > 1 ? n / 255 : n
  }
  const rr = to1(r)
  const gg = to1(g)
  const bb = to1(b)
  if (rr == null || gg == null || bb == null) return null
  return { r: rr, g: gg, b: bb }
}

function parseTransform(raw, THREE) {
  const m = new THREE.Matrix4()
  if (!raw) return m
  const t = raw.trim().split(/\s+/).map(Number)
  if (t.length !== 12 || t.some((n) => Number.isNaN(n))) return m
  m.set(t[0], t[3], t[6], t[9], t[1], t[4], t[7], t[10], t[2], t[5], t[8], t[11], 0, 0, 0, 1)
  return m
}

function findZipEntry(zip, predicate) {
  return Object.keys(zip.files).find((n) => !zip.files[n].dir && predicate(zipPath(n)))
}

function mimeFromPath(path) {
  const lower = path.toLowerCase()
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg'
  if (lower.endsWith('.webp')) return 'image/webp'
  return 'image/png'
}

function isProbablyBinary(name, _text) {
  const lower = zipPath(name).toLowerCase()
  return /\.(png|jpe?g|webp|stl|bin)$/i.test(lower)
}

/**
 * Inspect the 3MF ZIP immediately and dump structure + XML head to the console.
 * @returns {Promise<import('jszip')>}
 */
export async function inspectThreeMfArchive(buffer) {
  const zip = await JSZip.loadAsync(buffer)
  console.log('3MF Zip File Structure:', Object.keys(zip.files))

  const modelName = findZipEntry(
    zip,
    (n) => n.toLowerCase().endsWith('3d/3dmodel.model') || n.toLowerCase().endsWith('.model'),
  )
  if (modelName) {
    const xmlText = (await zip.file(modelName).async('string')).replace(/^\uFEFF/, '')
    console.log(`3MF ${modelName} (first 1000 chars):`, xmlText.slice(0, 1000))
  } else {
    console.warn('[3MF] 3D/3dmodel.model not found in archive')
  }

  const metaFiles = Object.keys(zip.files).filter((n) => {
    if (zip.files[n].dir) return false
    return zipPath(n).toLowerCase().startsWith('metadata/')
  })
  for (const name of metaFiles) {
    try {
      const text = (await zip.file(name).async('string')).replace(/^\uFEFF/, '')
      if (isProbablyBinary(name, text)) {
        console.log(`3MF ${name}: [binary asset]`)
        continue
      }
      console.log(`3MF ${name} (first 1000 chars):`, text.slice(0, 1000))
    } catch (err) {
      console.warn(`[3MF] could not read ${name}`, err)
    }
  }
  return zip
}

function parseXml(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText.replace(/^\uFEFF/, ''), 'application/xml')
  const err = doc.querySelector?.('parsererror')
  if (err) throw new Error(`3MF XML parse error: ${err.textContent?.slice(0, 180) || 'invalid XML'}`)
  return doc
}

function parseVertices(meshEl) {
  const positions = []
  const vertexColors = []
  let hasVertexXml = false
  const list = kids(meshEl, 'vertices')[0]
  let nodes = list ? kids(list, 'vertex') : []
  if (!nodes.length && list) nodes = allByTag(list, 'vertex')
  for (const v of nodes) {
    positions.push(Number(attr(v, 'x') || 0), Number(attr(v, 'y') || 0), Number(attr(v, 'z') || 0))
    const painted = parseHexColor(attr(v, 'color')) || rgb255(attr(v, 'r'), attr(v, 'g'), attr(v, 'b'))
    if (painted) {
      hasVertexXml = true
      vertexColors.push(painted.r, painted.g, painted.b)
    } else {
      vertexColors.push(Number.NaN, Number.NaN, Number.NaN)
    }
  }
  return { positions: new Float32Array(positions), vertexColors, hasVertexXml }
}

function parseTriangles(meshEl) {
  const triangles = []
  const list = kids(meshEl, 'triangles')[0]
  const nodes = list ? kids(list, 'triangle') : allByTag(meshEl, 'triangle')
  for (const t of nodes) {
    triangles.push({
      v1: Number(attr(t, 'v1') || 0),
      v2: Number(attr(t, 'v2') || 0),
      v3: Number(attr(t, 'v3') || 0),
      pid: attr(t, 'pid'),
      p1: attr(t, 'p1'),
      p2: attr(t, 'p2'),
      p3: attr(t, 'p3'),
      paint: attr(t, 'paint_color') || attr(t, 'paintcolor'),
    })
  }
  return triangles
}

function parseColorResources(doc) {
  const groups = Object.create(null)
  const colorPalette = []

  const ingest = (id, colors) => {
    if (id == null || id === '' || !colors.length) return
    groups[String(id)] = colors
    for (const c of colors) colorPalette.push(c)
  }

  for (const group of allByTag(doc, 'colorgroup')) {
    const colors = []
    for (const c of kids(group, 'color')) {
      const parsed = parseHexColor(attr(c, 'color'))
      if (parsed) colors.push(parsed)
    }
    ingest(attr(group, 'id'), colors)
  }
  for (const group of allByTag(doc, 'basematerials')) {
    const colors = []
    for (const c of kids(group, 'base')) {
      const parsed = parseHexColor(attr(c, 'displaycolor') || attr(c, 'displaycolour'))
      if (parsed) colors.push(parsed)
    }
    ingest(attr(group, 'id'), colors)
  }
  return { groups, colorPalette }
}

function parseTextureResources(doc) {
  const texture2d = Object.create(null)
  const texture2dgroup = Object.create(null)
  for (const el of allByTag(doc, 'texture2d')) {
    const id = attr(el, 'id')
    if (!id) continue
    texture2d[id] = {
      path: attr(el, 'path'),
      contenttype: attr(el, 'contenttype') || 'image/png',
    }
  }
  for (const el of allByTag(doc, 'texture2dgroup')) {
    const id = attr(el, 'id')
    if (!id) continue
    const uvs = []
    for (const c of kids(el, 'tex2coord')) {
      uvs.push(Number(attr(c, 'u') || 0), Number(attr(c, 'v') || 0))
    }
    texture2dgroup[id] = { texid: attr(el, 'texid'), uvs }
  }
  return { texture2d, texture2dgroup }
}

function parseMeshElement(meshEl, fallback) {
  const { positions, vertexColors, hasVertexXml } = parseVertices(meshEl)
  const triangles = parseTriangles(meshEl)
  return {
    ...fallback,
    positions,
    vertexColors,
    hasVertexXml,
    triangles,
  }
}

function parseObjectElement(el) {
  const id = attr(el, 'id')
  const base = {
    id,
    name: attr(el, 'name') || `object-${id}`,
    pid: attr(el, 'pid'),
    pindex: attr(el, 'pindex'),
    extruder: attr(el, 'extruder'),
    components: kids(kids(el, 'components')[0], 'component').map((c) => ({
      objectid: attr(c, 'objectid'),
      transform: attr(c, 'transform'),
      path: attr(c, 'path'),
    })),
  }

  const bodies = []
  for (const meshEl of kids(el, 'mesh')) {
    bodies.push(parseMeshElement(meshEl, { ...base, kind: 'object' }))
  }
  const volumeEls = [...kids(el, 'volume'), ...kids(el, 'mesh').flatMap((m) => kids(m, 'volume'))]
  for (const vol of volumeEls) {
    const volMesh = kids(vol, 'mesh')[0] || vol
    if (!kids(volMesh, 'triangles').length && !kids(volMesh, 'vertices').length) continue
    bodies.push(
      parseMeshElement(volMesh, {
        ...base,
        id: attr(vol, 'id') || `${id}-vol-${bodies.length}`,
        name: attr(vol, 'name') || `${base.name}-volume`,
        pid: attr(vol, 'pid') || base.pid,
        pindex: attr(vol, 'pindex') || base.pindex,
        extruder: attr(vol, 'extruder') || base.extruder,
        kind: 'volume',
      }),
    )
  }
  if (!bodies.length && kids(el, 'mesh').length === 0) {
    bodies.push({
      ...base,
      kind: 'assembly',
      positions: new Float32Array(0),
      vertexColors: [],
      hasVertexXml: false,
      triangles: [],
    })
  }
  return { meta: base, bodies }
}

function parseBuildItems(doc) {
  const items = []
  for (const build of allByTag(doc, 'build')) {
    for (const item of kids(build, 'item')) {
      const objectid = attr(item, 'objectid')
      if (objectid) items.push({ objectid, transform: attr(item, 'transform'), path: attr(item, 'path') })
    }
  }
  return items
}

function coercePalette(raw) {
  if (!raw) return []
  let parts = raw
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('[')) {
      try {
        parts = JSON.parse(trimmed)
      } catch {
        parts = trimmed.split(/[;,]+/)
      }
    } else {
      parts = trimmed.split(/[;,]+/)
    }
  }
  if (!Array.isArray(parts)) return []
  return parts.map((item) => parseHexColor(item)?.hex).filter(Boolean)
}

export function parseBambuFilamentPalette(text) {
  if (!text) return []
  const trimmed = text.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const json = JSON.parse(trimmed)
      const src =
        json.filament_colour ||
        json.filament_colors ||
        json.filament_colours ||
        json.default_filament_colour ||
        json.extruder_colour
      const pal = coercePalette(src)
      if (pal.length) return pal
    } catch {
      /* ignore */
    }
  }
  for (const key of ['filament_colour', 'filament_colors', 'filament_colours', 'default_filament_colour']) {
    const jsonish = new RegExp(`"${key}"\\s*:\\s*(\\[[\\s\\S]*?\\])`, 'i').exec(text)
    if (jsonish) {
      try {
        const pal = coercePalette(JSON.parse(jsonish[1]))
        if (pal.length) return pal
      } catch {
        const pal = coercePalette(jsonish[1])
        if (pal.length) return pal
      }
    }
  }
  return []
}

function parseModelSettingsExtruders(xmlText) {
  const map = Object.create(null)
  if (!xmlText) return map
  let doc
  try {
    doc = parseXml(xmlText)
  } catch {
    return map
  }
  for (const obj of allByTag(doc, 'object')) {
    const id = attr(obj, 'id')
    let extruder = null
    for (const meta of [...kids(obj, 'metadata'), ...allByTag(obj, 'metadata')].filter((m) => m.parentNode === obj)) {
      if (attr(meta, 'key') === 'extruder') extruder = attr(meta, 'value')
    }
    if (id && extruder) map[String(id)] = extruder
    for (const part of [...kids(obj, 'part'), ...allByTag(obj, 'part')]) {
      const pid = attr(part, 'id')
      let partExtruder = extruder
      for (const meta of kids(part, 'metadata')) {
        if (attr(meta, 'key') === 'extruder') partExtruder = attr(meta, 'value')
      }
      if (pid && partExtruder) map[String(pid)] = partExtruder
    }
  }
  return map
}

async function loadBambuSidecar(zip) {
  const filamentPalette = []
  const extruders = Object.create(null)
  for (const name of Object.keys(zip.files)) {
    if (zip.files[name].dir) continue
    const p = zipPath(name).toLowerCase()
    try {
      if (p.endsWith('metadata/project_settings.config') || p.endsWith('project_settings.config')) {
        const pal = parseBambuFilamentPalette(await zip.file(name).async('string'))
        if (pal.length) filamentPalette.splice(0, filamentPalette.length, ...pal)
      }
      if (p.endsWith('metadata/model_settings.config') || p.endsWith('model_settings.config')) {
        Object.assign(extruders, parseModelSettingsExtruders(await zip.file(name).async('string')))
      }
    } catch (err) {
      console.warn('[3MF] sidecar read failed', name, err)
    }
  }
  return { filamentPalette, extruders }
}

export function decodePaintSlot(paint) {
  if (paint == null || paint === '') return null
  const s = String(paint).trim()
  if (!s) return null
  const upper = s.toUpperCase()
  const exact = PAINT_SLOT_CODES.findIndex((c) => c === upper)
  if (exact >= 0) return exact + 1
  let rest = upper
  const found = []
  for (let i = PAINT_SLOT_CODES.length - 1; i >= 0; i -= 1) {
    const code = PAINT_SLOT_CODES[i]
    if (rest.includes(code)) {
      rest = rest.split(code).join('')
      found.push(i + 1)
    }
  }
  if (found.length) return Math.min(...found)
  if (/^\d+$/.test(s)) {
    const n = Number(s)
    return n > 0 ? n : null
  }
  return null
}

function toIndex(value, fallback = 0) {
  if (value == null || value === '') return fallback
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function lookupGroupColor(groups, pid, index, fallbackPid, modelPath) {
  const prefix = normalizeModelPath(modelPath)
  const keys = [
    prefix ? `${prefix}::${pid ?? ''}` : null,
    String(pid ?? ''),
    prefix ? `${prefix}::${fallbackPid ?? ''}` : null,
    String(fallbackPid ?? ''),
  ].filter((k) => k != null && k !== '' && k !== '::')
  for (const key of keys) {
    const group = groups[key]
    if (!group?.length) continue
    const idx = Math.max(0, Math.min(group.length - 1, toIndex(index, 0)))
    if (group[idx]) return group[idx]
  }
  return null
}

function standardMaterial(THREE, extras = {}) {
  const material = new THREE.MeshStandardMaterial({
    color: extras.color ?? 0xffffff,
    map: extras.map || null,
    vertexColors: Boolean(extras.vertexColors),
    roughness: 0.4,
    metalness: 0.1,
    side: THREE.DoubleSide,
    flatShading: false,
  })
  if (material.map) material.map.flipY = false
  material.userData.fromThreeMf = true
  if (material.color?.getHex) material.userData.nativeHex = material.color.getHex()
  material.needsUpdate = true
  return material
}

function attachColorAttribute(THREE, geometry, colorsFloat32Array) {
  const attribute = new THREE.BufferAttribute(colorsFloat32Array, 3)
  if ('colorSpace' in attribute && THREE.SRGBColorSpace) attribute.colorSpace = THREE.SRGBColorSpace
  attribute.needsUpdate = true
  geometry.setAttribute('color', attribute)
}

function resourceKind(pid, ctx) {
  const id = String(pid ?? '')
  if (ctx.texture2dgroup[id]) return 'texture-map'
  if (ctx.groups[id]) return ctx.groups[id].length > 1 ? 'colorgroup' : 'multi-body'
  return 'default'
}

function vertexRgbAt(body, index) {
  const i = index * 3
  const r = body.vertexColors[i]
  if (!Number.isFinite(r)) return null
  return { r, g: body.vertexColors[i + 1], b: body.vertexColors[i + 2] }
}

function colorForCorner(body, tri, cornerAttr, ctx, objectIndex) {
  const paintSlot = decodePaintSlot(tri.paint)
  if (paintSlot != null && ctx.filamentPalette?.length) {
    const hex = ctx.filamentPalette[paintSlot - 1] || ctx.filamentPalette[paintSlot]
    const fromSlot = parseHexColor(hex)
    if (fromSlot) return fromSlot
  }
  const painted = parseHexColor(tri.paint)
  if (painted) return painted
  const xml = vertexRgbAt(body, tri[cornerAttr === 'p1' ? 'v1' : cornerAttr === 'p2' ? 'v2' : 'v3'])
  if (xml) return xml
  const pid = tri.pid ?? body.pid
  const idx = tri[cornerAttr] ?? tri.p1 ?? body.pindex ?? 0
  const fromGroup = lookupGroupColor(ctx.groups, pid, idx, body.pid, body.modelPath)
  if (fromGroup) return fromGroup
  if (ctx.filamentPalette?.length) {
    const mapped = ctx.extruders?.[String(body.id)]
    const slot = toIndex(body.extruder ?? mapped, objectIndex + 1)
    const hex = ctx.filamentPalette[Math.max(0, slot - 1)] || ctx.filamentPalette[objectIndex % ctx.filamentPalette.length]
    return parseHexColor(hex)
  }
  if (ctx.colorPalette[0]) return ctx.colorPalette[0]
  return parseHexColor(DISTINCT_PALETTE[objectIndex % DISTINCT_PALETTE.length])
}

async function textureForPid(THREE, pid, ctx) {
  const group = ctx.texture2dgroup[String(pid)]
  if (!group) return null
  if (ctx.textures[group.texid]) return { tex: ctx.textures[group.texid], group }
  const rec = ctx.texture2d[group.texid]
  if (!rec?.path) return null
  const tex = await ctx.loadTexture(rec.path, rec.contenttype)
  if (tex) ctx.textures[group.texid] = tex
  return tex ? { tex, group } : null
}

function toThreeColor(THREE, rgb) {
  if (rgb?.hex) return new THREE.Color(rgb.hex)
  const c = new THREE.Color()
  if (!rgb) return c
  if (THREE.SRGBColorSpace) c.setRGB(rgb.r, rgb.g, rgb.b, THREE.SRGBColorSpace)
  else c.setRGB(rgb.r, rgb.g, rgb.b)
  return c
}

function pushVert(dest, src, vi) {
  dest.push(src[vi * 3], src[vi * 3 + 1], src[vi * 3 + 2])
}

async function buildMeshesForBody(THREE, body, ctx, objectIndex) {
  const { positions, triangles } = body
  if (!triangles.length || positions.length < 9) return []

  const buckets = Object.create(null)
  for (const tri of triangles) {
    const pid = tri.pid ?? body.pid ?? 'default'
    if (!buckets[pid]) buckets[pid] = []
    buckets[pid].push(tri)
  }

  const meshes = []
  let bucketIndex = 0
  for (const [pid, tris] of Object.entries(buckets)) {
    const kind = resourceKind(pid, ctx)
    const textured = kind === 'texture-map' ? await textureForPid(THREE, pid, ctx) : null
    const geometry = new THREE.BufferGeometry()
    let colorMode = kind
    let material

    if (textured) {
      const pos = []
      const uv = []
      const uvs = textured.group.uvs
      for (const tri of tris) {
        pushVert(pos, positions, tri.v1)
        pushVert(pos, positions, tri.v2)
        pushVert(pos, positions, tri.v3)
        const i1 = toIndex(tri.p1, 0)
        const i2 = toIndex(tri.p2, i1)
        const i3 = toIndex(tri.p3, i1)
        uv.push(uvs[i1 * 2] || 0, uvs[i1 * 2 + 1] || 0)
        uv.push(uvs[i2 * 2] || 0, uvs[i2 * 2 + 1] || 0)
        uv.push(uvs[i3 * 2] || 0, uvs[i3 * 2 + 1] || 0)
      }
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3))
      geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uv), 2))
      material = standardMaterial(THREE, { map: textured.tex })
      colorMode = 'texture-map'
    } else {
      const useVertexXml = body.hasVertexXml
      const useFaceProps = tris.some((t) => t.pid || t.p1 || t.p2 || t.p3 || t.paint) || ctx.groups[String(pid)]
      const uniform = new Set(tris.map((t) => String(t.paint || t.p1 || body.pindex || pid || '')))
      const solid = !useVertexXml && uniform.size <= 1 && !tris.some((t) => t.p2 || t.p3)

      if (solid && !useFaceProps && ctx.groups[String(pid)] == null && !body.pid) {
        const hex =
          ctx.filamentPalette[objectIndex % (ctx.filamentPalette.length || 1)] ||
          DISTINCT_PALETTE[objectIndex % DISTINCT_PALETTE.length]
        geometry.setAttribute('position', new THREE.BufferAttribute(positions.slice(), 3))
        geometry.setIndex(tris.flatMap((t) => [t.v1, t.v2, t.v3]))
        material = standardMaterial(THREE, { color: new THREE.Color(hex) })
        colorMode = 'multi-body'
      } else if (solid) {
        const rgb = colorForCorner(body, tris[0], 'p1', ctx, objectIndex + bucketIndex)
        geometry.setAttribute('position', new THREE.BufferAttribute(positions.slice(), 3))
        geometry.setIndex(tris.flatMap((t) => [t.v1, t.v2, t.v3]))
        material = standardMaterial(THREE, { color: toThreeColor(THREE, rgb) })
        colorMode = useVertexXml ? 'vertex-xml' : ctx.groups[String(pid)] || body.pid ? 'colorgroup' : 'multi-body'
      } else {
        const pos = []
        const colors = []
        for (const tri of tris) {
          const c1 = colorForCorner(body, tri, 'p1', ctx, objectIndex)
          const c2 = colorForCorner(body, tri, 'p2', ctx, objectIndex)
          const c3 = colorForCorner(body, tri, 'p3', ctx, objectIndex)
          pushVert(pos, positions, tri.v1)
          pushVert(pos, positions, tri.v2)
          pushVert(pos, positions, tri.v3)
          colors.push(c1.r, c1.g, c1.b, c2.r, c2.g, c2.b, c3.r, c3.g, c3.b)
        }
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3))
        attachColorAttribute(THREE, geometry, new Float32Array(colors))
        material = standardMaterial(THREE, { vertexColors: true, color: 0xffffff })
        colorMode = useVertexXml ? 'vertex-xml' : 'colorgroup'
      }
    }

    geometry.computeVertexNormals()
    const mesh = new THREE.Mesh(geometry, material)
    mesh.name = body.name
    mesh.userData.fromThreeMf = true
    mesh.userData.colorMode = colorMode
    mesh.userData.pid = pid
    meshes.push(mesh)
    bucketIndex += 1
  }
  return meshes
}

function collectEmbeddedTexturePaths(zip) {
  return Object.keys(zip.files).filter((n) => {
    if (zip.files[n].dir) return false
    const p = zipPath(n).toLowerCase()
    return /(?:^|\/)3d\/textures\/.+\.(png|jpe?g|webp)$/.test(p)
  })
}

async function makeTextureLoader(THREE, zip) {
  const cache = Object.create(null)
  return async function loadTexture(path, contenttype) {
    const key = zipPath(path).toLowerCase()
    if (cache[key]) return cache[key]
    const name =
      findZipEntry(zip, (n) => n.toLowerCase() === key || n.toLowerCase().endsWith(`/${key}`)) ||
      findZipEntry(zip, (n) => n.toLowerCase().endsWith(key.split('/').pop()))
    if (!name) return null
    const bytes = await zip.file(name).async('uint8array')
    const blob = new Blob([bytes], { type: contenttype || mimeFromPath(name) })
    const blobUrl = URL.createObjectURL(blob)
    try {
      const bitmap = await createImageBitmap(blob)
      const tex = new THREE.Texture(bitmap)
      tex.flipY = false
      tex.colorSpace = THREE.SRGBColorSpace
      tex.needsUpdate = true
      tex.userData.blobUrl = blobUrl
      cache[key] = tex
      return tex
    } catch (err) {
      console.warn('[3MF] texture decode failed', name, err)
      URL.revokeObjectURL(blobUrl)
      return null
    }
  }
}

function catalogLookup(catalog, id, fromPath) {
  const p = normalizeModelPath(fromPath)
  if (p && catalog[p]?.[id]) return catalog[p][id]
  const buckets = Object.values(catalog)
  const matches = buckets.map((b) => b[id]).filter(Boolean)
  if (matches.length === 1) return matches[0]
  if (p) {
    const same = matches.find((m) => normalizeModelPath(m.meta.modelPath) === p)
    if (same) return same
  }
  return matches[0] || null
}

function instantiate(id, catalog, THREE, stack = new Set(), objectIndex = 0, fromPath = '') {
  const rec = catalogLookup(catalog, id, fromPath)
  const group = new THREE.Group()
  group.userData.fromThreeMf = true
  const stackKey = rec
    ? `${normalizeModelPath(rec.meta.modelPath)}::${rec.meta.id}`
    : `${normalizeModelPath(fromPath)}::${id}`
  if (!rec || stack.has(stackKey)) return group
  stack.add(stackKey)
  group.name = rec.meta.name

  for (const mesh of rec.builtMeshes || []) {
    group.add(mesh.clone())
  }

  ;(rec.meta.components || []).forEach((comp, i) => {
    const childPath = comp.path || rec.meta.modelPath
    const child = instantiate(comp.objectid, catalog, THREE, stack, objectIndex + i + 1, childPath)
    child.applyMatrix4(parseTransform(comp.transform, THREE))
    group.add(child)
  })
  stack.delete(stackKey)
  return group
}

function ingestDoc(doc, modelPath, catalog, groups, texture2d, texture2dgroup) {
  const prefix = normalizeModelPath(modelPath)
  const parsedColors = parseColorResources(doc)
  Object.assign(groups, parsedColors.groups)
  for (const [id, colors] of Object.entries(parsedColors.groups)) {
    groups[`${prefix}::${id}`] = colors
  }
  const parsedTex = parseTextureResources(doc)
  Object.assign(texture2d, parsedTex.texture2d)
  Object.assign(texture2dgroup, parsedTex.texture2dgroup)
  const bucket = catalog[prefix] || (catalog[prefix] = Object.create(null))
  for (const el of allByTag(doc, 'object')) {
    const parsed = parseObjectElement(el)
    if (!parsed.meta.id) continue
    parsed.meta.modelPath = modelPath
    for (const body of parsed.bodies) body.modelPath = modelPath
    bucket[parsed.meta.id] = { ...parsed, index: Object.keys(bucket).length }
  }
  return parsedColors.colorPalette
}

function applyExtruders(catalog, extruders) {
  if (!extruders) return
  for (const bucket of Object.values(catalog)) {
    for (const rec of Object.values(bucket)) {
      const ext = extruders[String(rec.meta.id)]
      if (ext == null || ext === '') continue
      rec.meta.extruder = rec.meta.extruder || ext
      for (const body of rec.bodies) {
        if (body.extruder == null || body.extruder === '') body.extruder = ext
      }
    }
  }
}

function allRecords(catalog) {
  const out = []
  for (const bucket of Object.values(catalog)) {
    out.push(...Object.values(bucket))
  }
  return out
}

export async function unzipModelXml(buffer) {
  const zip = await JSZip.loadAsync(buffer)
  const modelName = findZipEntry(
    zip,
    (n) => n.toLowerCase().endsWith('3d/3dmodel.model') || n.toLowerCase().endsWith('.model'),
  )
  if (!modelName) return ''
  return (await zip.file(modelName).async('string')).replace(/^\uFEFF/, '')
}

export async function loadThreeMfGroup(THREE, buffer) {
  const zip = await inspectThreeMfArchive(buffer)
  const modelName = findZipEntry(
    zip,
    (n) => n.toLowerCase().endsWith('3d/3dmodel.model') || n.toLowerCase().endsWith('.model'),
  )
  if (!modelName) throw new Error('3MF içinde 3D/3dmodel.model yok.')
  const xmlText = (await zip.file(modelName).async('string')).replace(/^\uFEFF/, '')
  const doc = parseXml(xmlText)

  const catalog = Object.create(null)
  const groups = Object.create(null)
  const texture2d = Object.create(null)
  const texture2dgroup = Object.create(null)
  const colorPalette = ingestDoc(doc, modelName, catalog, groups, texture2d, texture2dgroup)

  for (const name of Object.keys(zip.files)) {
    if (zip.files[name].dir || name === modelName) continue
    if (!zipPath(name).toLowerCase().endsWith('.model')) continue
    ingestDoc(
      parseXml(await zip.file(name).async('string')),
      name,
      catalog,
      groups,
      texture2d,
      texture2dgroup,
    )
  }

  const { filamentPalette, extruders } = await loadBambuSidecar(zip)
  applyExtruders(catalog, extruders)
  const embeddedTextures = collectEmbeddedTexturePaths(zip)
  const loadTexture = await makeTextureLoader(THREE, zip)

  if (embeddedTextures.length) {
    console.log('[3MF] embedded textures:', embeddedTextures)
    for (const path of embeddedTextures) {
      const id = `file:${zipPath(path)}`
      if (!Object.values(texture2d).some((t) => zipPath(t.path || '').toLowerCase().endsWith(zipPath(path).toLowerCase()))) {
        texture2d[id] = { path, contenttype: mimeFromPath(path) }
      }
    }
  }

  const ctx = {
    groups,
    colorPalette,
    texture2d,
    texture2dgroup,
    textures: Object.create(null),
    loadTexture,
    filamentPalette,
    extruders,
  }

  let objectIndex = 0
  for (const rec of allRecords(catalog)) {
    rec.builtMeshes = []
    for (const body of rec.bodies) {
      const meshes = await buildMeshesForBody(THREE, body, ctx, objectIndex)
      rec.builtMeshes.push(...meshes)
    }
    objectIndex += 1
  }

  const scene = new THREE.Group()
  scene.name = '3mf'
  scene.userData.fromThreeMf = true

  const buildItems = parseBuildItems(doc)
  const items = buildItems.length
    ? buildItems
    : allRecords(catalog).map((rec) => ({
        objectid: rec.meta.id,
        transform: null,
        path: rec.meta.modelPath,
      }))

  items.forEach((item, i) => {
    const node = instantiate(item.objectid, catalog, THREE, new Set(), i, item.path || modelName)
    node.applyMatrix4(parseTransform(item.transform, THREE))
    scene.add(node)
  })

  const modes = new Set()
  let meshCount = 0
  scene.traverse((obj) => {
    if (!obj.isMesh) return
    meshCount += 1
    if (obj.userData.colorMode) modes.add(obj.userData.colorMode)
  })
  if (meshCount === 0) throw new Error('3MF içinde görüntülenecek mesh yok.')

  const objectEls = allByTag(doc, 'object')
  const volumeCount = allByTag(doc, 'volume').length
  let colorMode = 'none'
  if (modes.size === 1) colorMode = [...modes][0]
  else if (modes.size > 1) colorMode = 'mixed'
  else if (objectEls.length > 1 || volumeCount > 0) colorMode = 'multi-body'
  else if (embeddedTextures.length) colorMode = 'texture-map'
  else if (colorPalette.length) colorMode = 'colorgroup'

  scene.userData.colorMode = colorMode
  console.log('[3MF] Mode:', colorMode)
  console.log('[3MF] objects:', objectEls.length, 'volumes:', volumeCount, 'meshes:', meshCount)
  console.log('[3MF] colorgroup/basematerials entries:', colorPalette.length, 'filament palette:', filamentPalette)
  return scene
}

export function logThreeMfMeshes(root) {
  console.log('[3MF] Mode:', root.userData?.colorMode || 'unknown')
  root.traverse((child) => {
    if (!child.isMesh || !child.geometry) return
    console.log(
      '3MF Mesh:',
      child.name,
      'mode:',
      child.userData.colorMode,
      'Attributes:',
      child.geometry.attributes,
      'Material:',
      child.material,
    )
  })
}

function materialColorHex(color) {
  if (color == null) return null
  if (typeof color === 'number') return color >>> 0
  if (typeof color.getHex === 'function') return color.getHex()
  return null
}

export function materialHasNativeColor(mat) {
  if (!mat) return false
  const list = Array.isArray(mat) ? mat : [mat]
  return list.some((m) => {
    if (!m) return false
    if (m.vertexColors || m.map || m.userData?.fromThreeMf) return true
    const assigned = m.userData?.nativeHex
    const hex = materialColorHex(m.color)
    if (assigned != null && hex === assigned) return true
    if (hex == null) return false
    if (hex === FALLBACK_BEIGE) return false
    return !PLACEHOLDER_COLORS.has(hex)
  })
}

export function applyXmlColorsToThreeGroup(THREE, group, xmlText) {
  const doc = parseXml(xmlText)
  const { groups, colorPalette } = parseColorResources(doc)
  const objects = allByTag(doc, 'object').map((el) => parseObjectElement(el))
  const bodies = objects.flatMap((o) => o.bodies).filter((b) => b.triangles.length)
  const meshes = []
  group.traverse((child) => {
    if (child.isMesh) meshes.push(child)
  })
  const ctx = {
    groups,
    colorPalette,
    texture2d: {},
    texture2dgroup: {},
    textures: {},
    loadTexture: async () => null,
    filamentPalette: [],
    extruders: {},
  }
  meshes.forEach(async (mesh, i) => {
    const body = bodies[i]
    if (!body) return
    const built = await buildMeshesForBody(THREE, body, ctx, i)
    if (!built[0]) return
    mesh.geometry.dispose()
    mesh.geometry = built[0].geometry
    mesh.material = built[0].material
    mesh.userData.fromThreeMf = true
    mesh.userData.colorMode = built[0].userData.colorMode
  })
}

export { inspectThreeMfArchive as inspectThreeMfZip, FALLBACK_BEIGE, PLACEHOLDER_COLORS }
