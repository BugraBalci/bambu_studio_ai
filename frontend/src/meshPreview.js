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
    metalness: 0.12,
    roughness: 0.46,
    side: THREE.DoubleSide,
  })
}

function prepareObject(THREE, root) {
  let shared = null
  root.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return
    if (!obj.geometry.attributes.normal) obj.geometry.computeVertexNormals()
    if (!obj.material) {
      if (!shared) shared = fallbackMaterial(THREE)
      obj.material = shared
      return
    }
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    mats.forEach((m) => {
      if (m) m.side = THREE.DoubleSide
    })
  })
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
        if (value && value.isTexture) value.dispose()
      })
      mat.dispose()
    })
  })
}

function frameCamera(THREE, camera, object) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  object.position.sub(center)
  object.updateMatrixWorld(true)

  const maxDim = Math.max(size.x, size.y, size.z, 1e-6)
  const fov = (camera.fov * Math.PI) / 180
  const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.65
  const dir = new THREE.Vector3(1.08, 0.86, 1.28).normalize()
  camera.position.copy(dir.multiplyScalar(dist))
  camera.near = Math.max(dist / 120, 0.01)
  camera.far = dist * 24
  camera.lookAt(0, 0, 0)
  camera.updateProjectionMatrix()
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

  prepareObject(THREE, object)
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
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.12

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0c1016)
    scene.add(object)

    scene.add(new THREE.HemisphereLight(0xb8c6d8, 0x1a1510, 1.15))
    const key = new THREE.DirectionalLight(0xfff4e6, 1.35)
    key.position.set(2.4, 3.2, 1.6)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0x8aa4c4, 0.55)
    fill.position.set(-2.2, 0.4, 1.8)
    scene.add(fill)
    const rim = new THREE.DirectionalLight(0xe8953a, 0.55)
    rim.position.set(-0.6, 1.8, -2.4)
    scene.add(rim)

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
