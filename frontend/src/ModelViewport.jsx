import { useEffect, useRef } from 'react'
import { frameOrbitCamera, loadAlignedPreviewObject, slicerOverlayGeometry } from './meshPreview'

/**
 * Live Three.js print-bed viewport: Z-up correction, orbit / pan / zoom,
 * optional text-volume overlay from the backend engine.
 */
export default function ModelViewport({ file, onReady, onError, overlay = null }) {
  const hostRef = useRef(null)
  const ctxRef = useRef(null)
  const overlayRef = useRef(overlay)
  overlayRef.current = overlay

  function applyOverlay(ctx, nextOverlay) {
    if (!ctx?.THREE || !ctx.scene) return
    const { THREE, scene } = ctx
    if (ctx.overlayMesh) {
      scene.remove(ctx.overlayMesh)
      ctx.overlayMesh.geometry?.dispose()
      ctx.overlayMesh.material?.dispose()
      ctx.overlayMesh = null
    }
    if (!nextOverlay?.enabled || !nextOverlay.vertices?.length) return
    const geometry = slicerOverlayGeometry(THREE, nextOverlay, ctx.hostBox)
    if (!geometry) return
    const color = nextOverlay.color_hex || (nextOverlay.style === 'embossed' ? '#e8c547' : '#1c1c1c')
    const material = new THREE.MeshStandardMaterial({
      color,
      metalness: 0.08,
      roughness: 0.42,
      transparent: nextOverlay.style === 'flush',
      opacity: nextOverlay.style === 'flush' ? 0.88 : 1,
      emissive: nextOverlay.style === 'embossed' ? 0x3a2a10 : 0x000000,
      emissiveIntensity: nextOverlay.style === 'embossed' ? 0.18 : 0,
      side: THREE.DoubleSide,
    })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.renderOrder = 2
    scene.add(mesh)
    ctx.overlayMesh = mesh
  }

  useEffect(() => {
    if (!file || !hostRef.current) return

    const host = hostRef.current
    let cancelled = false
    let renderer
    let controls
    let raf = 0
    let resizeObserver
    let disposeMesh = () => {}

    ;(async () => {
      try {
        const { THREE, object, stats, dispose } = await loadAlignedPreviewObject(file)
        disposeMesh = dispose
        if (cancelled) {
          dispose()
          return
        }

        const { OrbitControls } = await import('three/addons/controls/OrbitControls.js')
        if (cancelled) {
          dispose()
          return
        }

        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0x0c1016)

        scene.add(new THREE.AmbientLight(0xffffff, 1.05))
        const key = new THREE.DirectionalLight(0xffffff, 1.45)
        key.position.set(6, 12, 8)
        scene.add(key)
        const fill = new THREE.DirectionalLight(0x9eb6d4, 0.45)
        fill.position.set(-8, 4, -6)
        scene.add(fill)

        scene.add(object)

        const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 2000)
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
        renderer.setClearColor(0x0c1016, 1)
        renderer.outputColorSpace = THREE.SRGBColorSpace
        renderer.toneMapping = THREE.NoToneMapping
        renderer.domElement.className = 'preview-canvas'
        renderer.domElement.style.touchAction = 'none'
        host.innerHTML = ''
        host.appendChild(renderer.domElement)

        controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        controls.dampingFactor = 0.05
        controls.enablePan = true
        controls.enableZoom = true
        controls.screenSpacePanning = true
        controls.zoomToCursor = true

        const framed = frameOrbitCamera(THREE, camera, controls, object)
        const grid = new THREE.GridHelper(
          Math.max(framed.maxDim * 2.4, 20),
          20,
          0x3d4a5c,
          0x1c2430,
        )
        scene.add(grid)

        const hostBox = new THREE.Box3().setFromObject(object)
        ctxRef.current = { THREE, scene, object, overlayMesh: null, hostBox }
        applyOverlay(ctxRef.current, overlayRef.current)

        const resize = () => {
          if (!host.clientWidth || !host.clientHeight) return
          const w = host.clientWidth
          const h = host.clientHeight
          camera.aspect = w / Math.max(h, 1)
          camera.updateProjectionMatrix()
          renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
          renderer.setSize(w, h, false)
        }
        resize()
        resizeObserver = new ResizeObserver(resize)
        resizeObserver.observe(host)

        const tick = () => {
          if (cancelled) return
          raf = requestAnimationFrame(tick)
          controls.update()
          renderer.render(scene, camera)
        }
        tick()
        onReady?.(stats)
      } catch (err) {
        if (!cancelled) onError?.(err?.message || '3D görünüm yüklenemedi.')
      }
    })()

    return () => {
      cancelled = true
      ctxRef.current = null
      cancelAnimationFrame(raf)
      resizeObserver?.disconnect()
      controls?.dispose()
      if (renderer) {
        renderer.dispose()
        renderer.forceContextLoss?.()
        renderer.domElement?.remove()
      }
      disposeMesh()
      host.innerHTML = ''
    }
  }, [file])

  useEffect(() => {
    applyOverlay(ctxRef.current, overlay)
  }, [overlay])

  return <div ref={hostRef} className="preview-viewport" />
}
