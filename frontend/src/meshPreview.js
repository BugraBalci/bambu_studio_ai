import { loadThreeMfGroup, logThreeMfMeshes, materialHasNativeColor } from './loadThreeMf'

const PREVIEW_PX = 640
const MESH_COLOR = 0xf2d4a8

export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return '—'
  const n = Number(bytes)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

export function formatCount(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString('tr-TR')
}

function extensionOf(name = '') {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

function isZUpSource(filename = '', object, THREE) {
  const ext = extensionOf(filename)
  if (ext === '.3mf' || ext === '.stl') return true
  if (ext === '.glb' || ext === '.gltf') {
    const box = new THREE.Box3().setFromObject(object)
    const size = box.getSize(new THREE.Vector3())
    // CAD/slicer GLBs often store height on Z; glTF-native assets are already Y-up.
    return size.z > size.y * 1.12
  }
  if (ext === '.obj') {
    const box = new THREE.Box3().setFromObject(object)
    const size = box.getSize(new THREE.Vector3())
    return size.z >= size.y
  }
  return false
}

/**
 * 3MF/STL (and many CAD GLBs) are Z-up; Three.js is Y-up.
 * Rotate -90° about X, then center on XZ and sit the mesh on Y = 0.
 */
export function alignModelOrientation(THREE, root, filename = '') {
  root.updateMatrixWorld(true)
  if (isZUpSource(filename, root, THREE)) {
    root.rotation.x = -Math.PI / 2
    root.updateMatrixWorld(true)
  }

  root.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return
    if (obj.geometry.center && !obj.userData?.skipCenter) {
      // Keep assembly parts in their authored offsets; only isolated STL meshes center locally.
      if (extensionOf(filename) === '.stl') obj.geometry.center()
    }
  })
  root.updateMatrixWorld(true)

  const box = new THREE.Box3().setFromObject(root)
  if (box.isEmpty()) return
  const center = box.getCenter(new THREE.Vector3())
  root.position.x -= center.x
  root.position.z -= center.z
  root.position.y -= box.min.y
  root.updateMatrixWorld(true)
}

function meshStats(root) {
  let triangleCount = 0
  let vertexCount = 0
  root.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return
    const geom = obj.geometry
    const pos = geom.getAttribute('position')
    if (!pos) return
    vertexCount += pos.count
    if (geom.index) triangleCount += geom.index.count / 3
    else triangleCount += pos.count / 3
  })
  return {
    triangleCount: Math.round(triangleCount),
    vertexCount: Math.round(vertexCount),
  }
}

function fallbackMaterial(THREE) {
  return new THREE.MeshStandardMaterial({
    color: MESH_COLOR,
    metalness: 0.08,
    roughness: 0.48,
    side: THREE.DoubleSide,
  })
}

function cloneAsStandard(THREE, source, extras = {}) {
  const color = source?.color ? source.color.clone() : new THREE.Color(MESH_COLOR)
  return new THREE.MeshStandardMaterial({
    color,
    map: source?.map || null,
    vertexColors: Boolean(extras.vertexColors ?? source?.vertexColors),
    metalness: 0.1,
    roughness: 0.4,
    opacity: source?.opacity ?? 1,
    transparent: Boolean(source?.transparent) || (source?.opacity != null && source.opacity < 0.999),
    side: THREE.DoubleSide,
    flatShading: false,
    name: source?.name || '',
  })
}

function prepareObject(THREE, root, { isThreeMf = false, isGltf = false } = {}) {
  let sharedFallback = null
  root.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return
    if (!obj.geometry.attributes.normal) obj.geometry.computeVertexNormals()

    const hasVerts = Boolean(obj.geometry.getAttribute('color'))
    const mats = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []

    if (isThreeMf || obj.userData?.fromThreeMf) {
      const next = mats.length ? mats : [null]
      obj.material = next.length === 1
        ? finishThreeMfMaterial(THREE, next[0], obj)
        : next.map((m) => finishThreeMfMaterial(THREE, m, obj))
      return
    }

    const native =
      hasVerts ||
      mats.some((m) => materialHasNativeColor(m)) ||
      (isGltf && mats.some((m) => m && (m.color || m.map || m.vertexColors)))

    if (isGltf) {
      const m = mats[0]
      const hex = m?.color?.getHex?.()
      console.log(
        '[GLB Material]:',
        obj.name || '(unnamed)',
        hex != null ? `#${hex.toString(16).padStart(6, '0')}` : '(none)',
        'map:',
        Boolean(m?.map),
        'vertexColors:',
        Boolean(hasVerts || m?.vertexColors),
        'native:',
        native,
      )
    }

    if (!native) {
      if (!sharedFallback) sharedFallback = fallbackMaterial(THREE)
      obj.material = sharedFallback
      return
    }

    const next = mats.map((m) => {
      if (!m) return fallbackMaterial(THREE)
      if (m.isMeshStandardMaterial) {
        m.side = THREE.DoubleSide
        m.roughness = 0.4
        m.metalness = 0.1
        if (hasVerts) {
          m.vertexColors = true
          m.color.setHex(0xffffff)
        }
        return m
      }
      return cloneAsStandard(THREE, m, { vertexColors: hasVerts })
    })
    obj.material = next.length === 1 ? next[0] : next
  })
}

function finishThreeMfMaterial(THREE, source, mesh) {
  const hasVerts = Boolean(mesh.geometry.getAttribute('color'))
  const material = source?.isMaterial
    ? source
    : new THREE.MeshStandardMaterial({ color: source?.color || 0xffffff })
  material.roughness = 0.4
  material.metalness = 0.1
  material.side = THREE.DoubleSide
  if (hasVerts) {
    material.vertexColors = true
    material.color.setHex(0xffffff)
  }
  if (material.map) {
    material.map.flipY = false
    material.map.needsUpdate = true
  }
  material.needsUpdate = true
  return material
}

function parseGltf(GLTFLoader, buffer) {
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(
      buffer,
      '',
      (gltf) => resolve(gltf.scene || gltf.scenes?.[0]),
      (err) => reject(err instanceof Error ? err : new Error(String(err))),
    )
  })
}

async function loadObject(THREE, loaders, file) {
  const buffer = await file.arrayBuffer()
  const ext = extensionOf(file.name)

  if (ext === '.stl') {
    const geometry = new loaders.STLLoader().parse(buffer)
    return new THREE.Mesh(geometry, fallbackMaterial(THREE))
  }

  if (ext === '.obj') {
    const text = new TextDecoder().decode(buffer)
    return new loaders.OBJLoader().parse(text)
  }

  if (ext === '.glb' || ext === '.gltf') {
    const scene = await parseGltf(loaders.GLTFLoader, buffer)
    if (!scene) throw new Error('GLTF sahnesi boş.')
    return scene
  }

  if (ext === '.3mf') {
    return loadThreeMfGroup(THREE, buffer.slice(0))
  }

  throw new Error('Desteklenmeyen 3D format.')
}

function disposeObject(root) {
  const seen = new Set()
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose()
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((mat) => {
      if (!mat || seen.has(mat)) return
      seen.add(mat)
      Object.values(mat).forEach((value) => {
        if (value && value.isTexture) {
          if (value.userData?.blobUrl) URL.revokeObjectURL(value.userData.blobUrl)
          value.dispose()
        }
      })
      mat.dispose()
    })
  })
}

function frameCamera(THREE, camera, object) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())

  const maxDim = Math.max(size.x, size.y, size.z, 1e-6)
  const fov = (camera.fov * Math.PI) / 180
  const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.65
  const dir = new THREE.Vector3(1.08, 0.86, 1.28).normalize()
  camera.position.copy(center).add(dir.multiplyScalar(dist))
  camera.near = Math.max(dist / 120, 0.01)
  camera.far = dist * 24
  camera.lookAt(center)
  camera.updateProjectionMatrix()
}

export function frameOrbitCamera(THREE, camera, controls, object) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const maxDim = Math.max(size.x, size.y, size.z, 1e-6)
  const fov = (camera.fov * Math.PI) / 180
  const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.85
  const dir = new THREE.Vector3(1.15, 0.72, 1.35).normalize()
  camera.position.copy(center).add(dir.clone().multiplyScalar(dist))
  camera.near = Math.max(dist / 140, 0.01)
  camera.far = dist * 30
  camera.updateProjectionMatrix()
  if (controls) {
    controls.target.copy(center)
    controls.minDistance = Math.max(maxDim * 0.35, 0.05)
    controls.maxDistance = maxDim * 14
    controls.update()
  } else {
    camera.lookAt(center)
  }
  return { size, center, maxDim }
}

function setupPreviewLights(THREE, scene) {
  scene.add(new THREE.AmbientLight(0xffffff, 1.2))
  const key = new THREE.DirectionalLight(0xffffff, 1.5)
  key.position.set(5, 10, 7)
  scene.add(key)
}

/**
 * Parse a mesh file and snapshot a high-contrast 2D thumbnail.
 * Three.js is loaded on demand so the initial UI bundle stays small.
 * @param {File} file
 * @returns {Promise<{ dataUrl: string, triangleCount: number, vertexCount: number }>}
 */
export async function renderMeshThumbnail(file) {
  const THREE = await import('three')
  const [{ GLTFLoader }, { OBJLoader }, { STLLoader }] = await Promise.all([
    import('three/addons/loaders/GLTFLoader.js'),
    import('three/addons/loaders/OBJLoader.js'),
    import('three/addons/loaders/STLLoader.js'),
  ])

  let object
  try {
    object = await loadObject(THREE, { GLTFLoader, OBJLoader, STLLoader }, file)
  } catch (err) {
    const detail = err?.message || String(err)
    throw new Error(`Model okunamadı veya bozuk: ${detail}`)
  }
  object.updateMatrixWorld(true)

  let found = false
  object.traverse((obj) => {
    if (obj.isMesh) found = true
  })
  if (!found) {
    disposeObject(object)
    throw new Error('Dosyada görüntülenecek mesh yok.')
  }

  const ext = extensionOf(file.name)
  prepareObject(THREE, object, { isThreeMf: ext === '.3mf', isGltf: ext === '.glb' || ext === '.gltf' })
  alignModelOrientation(THREE, object, file.name)
  if (ext === '.3mf') logThreeMfMeshes(object)
  const stats = meshStats(object)

  const canvas = document.createElement('canvas')
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: 'low-power',
  })

  try {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(PREVIEW_PX, PREVIEW_PX, false)
    renderer.setClearColor(0x0c1016, 1)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.NoToneMapping
    renderer.toneMappingExposure = 1.0

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0c1016)
    scene.add(object)
    setupPreviewLights(THREE, scene)

    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 1000)
    frameCamera(THREE, camera, object)

    renderer.render(scene, camera)
    const dataUrl = canvas.toDataURL('image/png')
    if (!dataUrl || dataUrl === 'data:,') {
      throw new Error('Önizleme görüntüsü üretilemedi.')
    }
    return { dataUrl, ...stats }
  } finally {
    disposeObject(object)
    renderer.dispose()
    renderer.forceContextLoss?.()
  }
}

/**
 * Load a print mesh, apply materials + Z-up alignment. Caller owns disposal.
 */
export async function loadAlignedPreviewObject(file) {
  const THREE = await import('three')
  const [{ GLTFLoader }, { OBJLoader }, { STLLoader }] = await Promise.all([
    import('three/addons/loaders/GLTFLoader.js'),
    import('three/addons/loaders/OBJLoader.js'),
    import('three/addons/loaders/STLLoader.js'),
  ])
  const object = await loadObject(THREE, { GLTFLoader, OBJLoader, STLLoader }, file)
  object.updateMatrixWorld(true)
  let found = false
  object.traverse((obj) => {
    if (obj.isMesh) found = true
  })
  if (!found) {
    disposeObject(object)
    throw new Error('Dosyada görüntülenecek mesh yok.')
  }
  const ext = extensionOf(file.name)
  prepareObject(THREE, object, { isThreeMf: ext === '.3mf', isGltf: ext === '.glb' || ext === '.gltf' })
  alignModelOrientation(THREE, object, file.name)
  return { THREE, object, stats: meshStats(object), dispose: () => disposeObject(object) }
}
