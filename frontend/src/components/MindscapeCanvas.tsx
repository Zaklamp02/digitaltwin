import { useCallback, useEffect, useRef } from "react";

/* ══════════════════════════════════════════════════════════════════════
   Types
   ══════════════════════════════════════════════════════════════════════ */

export interface GraphNode {
  id: string;
  type: string;
  title: string;
  tier: number;
  edge_count: number;
  roles: string[];
  has_document: boolean;
  featured?: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
}

/** Internal positioned node used by the canvas layout */
interface LayoutNode extends GraphNode {
  wx: number;
  wy: number;
  r: number;
  /** child nodes (tier+1 neighbours connected via containment edges) */
  children: ChildNode[];
}

interface ChildNode {
  id: string;
  title: string;
  dx: number;
  dy: number;
  r: number;
  /** number of sub-children (for badge) */
  childCount: number;
}

interface Camera {
  x: number;
  y: number;
  z: number;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  a: number;
}

interface Drift {
  ph: number;
  ax: number;
  ay: number;
  fx: number;
  fy: number;
}

/* ══════════════════════════════════════════════════════════════════════
   Constants
   ══════════════════════════════════════════════════════════════════════ */

const CONTAINMENT_EDGES = new Set([
  "has", "includes", "nb_page", "member_of", "studied_at",
]);

/** Preferred positions for known nodes (world coords, center = 0,0).
 *  Nodes not in this map get auto-positioned in a ring. */

const POSITIONS: Record<string, [number, number]> = {
  career:      [170, -170],
  education:   [230,  30],
  hobbies:     [-170, 170],
  community:   [-230, -30],
  personality: [-30, -200],
  "nb-work":   [30,  170],
};

const RADII: Record<string, number> = {
  career: 24, education: 21, hobbies: 21,
  community: 19, personality: 19, "nb-work": 22,
};

/** Compute default (unfocused) zoom so all root nodes fit horizontally.
 *  Root positions span ±230 + node radius ≈ 254 world-units from centre. */
function getDefaultZoom(canvasW: number): number {
  const MAX_EXTENT = 254; // max world-x of outermost node centre + radius
  const MARGIN = 30;      // px breathing room on each side
  const fit = (canvasW / 2 - MARGIN) / MAX_EXTENT;
  return Math.min(fit, 1.35);  // cap at desktop max
}

/** Compute focus zoom so child ring fits horizontally.
 *  Children extend up to dx≈60 × spread 2.4 ≈ 144 world-units from centre. */
function getFocusZoom(canvasW: number): number {
  const MAX_CHILD_EXTENT = 150; // world-units (dx*spread + label slack)
  const MARGIN = 35;
  const fit = (canvasW / 2 - MARGIN) / MAX_CHILD_EXTENT;
  return Math.min(fit, 2.2);   // cap at desktop max
}

const _INIT_W = typeof window !== "undefined" ? window.innerWidth : 1200;
const _INIT_H = typeof window !== "undefined" ? window.innerHeight : 900;
const DEFAULT_ZOOM = getDefaultZoom(_INIT_W);

/** Vertical camera offset so graph sits between hero overlay and input bar.
 *  Hero content ≈ top 22%, input bar ≈ bottom 65px. */
function getDefaultCamY(canvasW: number, canvasH: number): number {
  const heroH = Math.min(canvasH * 0.22, 200); // hero overlay height (px)
  const inputH = 65;                             // input bar height (px)
  const usableCenter = heroH + (canvasH - heroH - inputH) / 2;
  const shiftPx = usableCenter - canvasH / 2;    // how far below screen center
  return -(shiftPx / getDefaultZoom(canvasW));    // negative = moves rendered world down
}

const DEFAULT_CAM_Y = getDefaultCamY(_INIT_W, _INIT_H);
const CAM_SPEED = 0.05;
const PARTICLE_COUNT = 130;

/* ══════════════════════════════════════════════════════════════════════
   Layout: convert flat graph data into positioned nodes
   ══════════════════════════════════════════════════════════════════════ */

function buildLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { layout: LayoutNode[]; layoutEdges: [number, number][] } {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // Adjacency for containment edges
  const children = new Map<string, string[]>();
  for (const e of edges) {
    if (!CONTAINMENT_EDGES.has(e.type)) continue;
    const list = children.get(e.source) ?? [];
    if (!list.includes(e.target)) list.push(e.target);
    children.set(e.source, list);
  }

  // Top-level nodes: all nodes with featured flag
  const featuredNodes = nodes.filter((n) => n.featured);
  const topNodes: LayoutNode[] = [];
  const topIds = new Set<string>();

  // Auto-position featured nodes that don't have a hardcoded position
  const unpositioned = featuredNodes.filter((n) => !POSITIONS[n.id]);
  const RING_R = 180;
  for (let i = 0; i < unpositioned.length; i++) {
    const angle = (i / unpositioned.length) * Math.PI * 2 - Math.PI / 2;
    POSITIONS[unpositioned[i].id] = [
      Math.round(Math.cos(angle) * RING_R),
      Math.round(Math.sin(angle) * RING_R),
    ];
  }

  for (const n of featuredNodes) {
    const pos = POSITIONS[n.id] ?? [0, 0];
    const childIds = children.get(n.id) ?? [];
    const angle0 = Math.random() * Math.PI * 2;

    topNodes.push({
      ...n,
      wx: pos[0],
      wy: pos[1],
      r: RADII[n.id] ?? 20,
      children: childIds
        .map((cid, i) => {
          const cn = nodeMap.get(cid);
          if (!cn) return null;
          const a = angle0 + (i / childIds.length) * Math.PI * 2;
          const subChildCount = (children.get(cid) ?? []).filter((id) => nodeMap.has(id)).length;
          return {
            id: cid,
            title: cn.title,
            dx: Math.cos(a) * (45 + Math.random() * 15),
            dy: Math.sin(a) * (30 + Math.random() * 15),
            r: 10,
            childCount: subChildCount,
          };
        })
        .filter(Boolean) as LayoutNode["children"],
    });
    topIds.add(n.id);
  }

  // Build edge list between top-level nodes
  const topIndex = new Map(topNodes.map((n, i) => [n.id, i]));
  const layoutEdges: [number, number][] = [];
  const edgeSeen = new Set<string>();
  for (const e of edges) {
    const si = topIndex.get(e.source);
    const ti = topIndex.get(e.target);
    if (si !== undefined && ti !== undefined && si !== ti) {
      const key = si < ti ? `${si}-${ti}` : `${ti}-${si}`;
      if (!edgeSeen.has(key)) {
        edgeSeen.add(key);
        layoutEdges.push([si, ti]);
      }
    }
  }

  // Add cross-connections: if a child of A is also a child of B, connect A-B
  for (let i = 0; i < topNodes.length; i++) {
    const childSet = new Set(topNodes[i].children.map((c) => c.id));
    for (let j = i + 1; j < topNodes.length; j++) {
      const has = topNodes[j].children.some((c) => childSet.has(c.id));
      if (has) {
        const key = `${i}-${j}`;
        if (!edgeSeen.has(key)) {
          edgeSeen.add(key);
          layoutEdges.push([i, j]);
        }
      }
    }
  }

  return { layout: topNodes, layoutEdges };
}

/** Build a layout centered on a specific node (used when diving into children). */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function buildDiveLayout(
  centerNodeId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
): { layout: LayoutNode[]; layoutEdges: [number, number][] } {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const centerNode = nodeMap.get(centerNodeId);
  if (!centerNode) return { layout: [], layoutEdges: [] };

  const childrenOf = new Map<string, string[]>();
  for (const e of edges) {
    if (!CONTAINMENT_EDGES.has(e.type)) continue;
    const list = childrenOf.get(e.source) ?? [];
    if (!list.includes(e.target)) list.push(e.target);
    childrenOf.set(e.source, list);
  }

  const childIds = (childrenOf.get(centerNodeId) ?? []).filter((id) => nodeMap.has(id));

  // Center as a layout node at 0,0
  const angle0 = Math.random() * Math.PI * 2;
  const centerLayout: LayoutNode = {
    ...centerNode,
    wx: 0,
    wy: 0,
    r: 26,
    children: childIds.map((cid, i) => {
      const cn = nodeMap.get(cid)!;
      const a = angle0 + (i / childIds.length) * Math.PI * 2;
      const subChildCount = (childrenOf.get(cid) ?? []).filter((id) => nodeMap.has(id)).length;
      return {
        id: cid,
        title: cn.title,
        dx: Math.cos(a) * (45 + Math.random() * 15),
        dy: Math.sin(a) * (30 + Math.random() * 15),
        r: 10,
        childCount: subChildCount,
      };
    }),
  };

  return { layout: [centerLayout], layoutEdges: [] };
}

/* ══════════════════════════════════════════════════════════════════════
   Component
   ══════════════════════════════════════════════════════════════════════ */

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  dark: boolean;
  onNodeFocus: (node: { id: string; title: string } | null) => void;
  focusedNodeId: string | null;
}

export function MindscapeCanvas({ nodes, edges, dark, onNodeFocus, focusedNodeId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef({
    cam: { x: 0, y: DEFAULT_CAM_Y, z: DEFAULT_ZOOM } as Camera,
    camTarget: { x: 0, y: DEFAULT_CAM_Y, z: DEFAULT_ZOOM } as Camera,
    time: 0,
    hoveredNode: null as LayoutNode | null,
    hoveredChild: null as ChildNode | null,
    dragging: false,
    dragStart: { x: 0, y: 0 },
    camAtDragStart: { x: 0, y: 0 },
    dragDistance: 0,
    pinching: false,
    pinchStartDist: 0,
    zoomAtPinchStart: 1,
    mouse: { x: -9999, y: -9999 },
    childExpandT: 0,
    particles: [] as Particle[],
    drifts: [] as Drift[],
    W: 0,
    H: 0,
    rafId: 0,
    /** Stack of node IDs for depth traversal (empty = root view) */
    diveStack: [] as string[],
    /** Transition progress for ring crossfade (0 = old, 1 = new) */
    ringFadeT: 1,
    /** Direction of transition: 1 = diving in, -1 = backing out */
    ringFadeDir: 1 as 1 | -1,
    /** Cooldown timestamp — ignore clicks for 500ms after a dive */
    lastDiveTime: 0,
    /** When true, the click handler is managing the transition — skip sync effect */
    skipSync: false,
  });

  const layoutRef = useRef<LayoutNode[]>([]);
  const layoutEdgesRef = useRef<[number, number][]>([]);
  const focusedRef = useRef<LayoutNode | null>(null);
  /** Root layout (saved when diving, restored when backing out) */
  const rootLayoutRef = useRef<{ layout: LayoutNode[]; edges: [number, number][] } | null>(null);

  // Rebuild layout when graph data changes
  useEffect(() => {
    if (!nodes.length) return;
    const s = stateRef.current;
    // If we're dived, rebuild the dive layout; otherwise build root
    if (s.diveStack.length > 0) {
      const currentDive = s.diveStack[s.diveStack.length - 1];
      const { layout: l, layoutEdges: le } = buildDiveLayout(currentDive, nodes, edges);
      layoutRef.current = l;
      layoutEdgesRef.current = le;
    } else {
      const { layout: l, layoutEdges: le } = buildLayout(nodes, edges);
      layoutRef.current = l;
      layoutEdgesRef.current = le;
      rootLayoutRef.current = { layout: l, edges: le };
    }

    // Init particles & drifts if not already
    if (s.particles.length === 0) {
      s.particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: (Math.random() - 0.5) * 900,
        y: (Math.random() - 0.5) * 650,
        vx: (Math.random() - 0.5) * 0.06,
        vy: (Math.random() - 0.5) * 0.06,
        r: 0.8 + Math.random() * 2.2,
        a: 0.03 + Math.random() * 0.08,
      }));
    }
    // One drift per layout node
    s.drifts = layoutRef.current.map(() => ({
      ph: Math.random() * Math.PI * 2,
      ax: 4 + Math.random() * 6,
      ay: 4 + Math.random() * 6,
      fx: 0.2 + Math.random() * 0.3,
      fy: 0.2 + Math.random() * 0.3,
    }));
  }, [nodes, edges]);

  // Sync focused node from parent
  useEffect(() => {
    const s = stateRef.current;
    // Skip if the click handler is managing the transition
    if (s.skipSync) {
      s.skipSync = false;
      return;
    }
    if (focusedNodeId) {
      // Check if it's a layout node in current layout
      const node = layoutRef.current.find((n) => n.id === focusedNodeId) ?? null;
      focusedRef.current = node;
      if (node) {
        const wp = nodeWorldPos(node, s.drifts, layoutRef.current, s.time);
        s.camTarget.x = wp.x;
        s.camTarget.y = wp.y - 20;
        s.camTarget.z = getFocusZoom(s.W || window.innerWidth);
      }
    } else {
      focusedRef.current = null;
      // Reset dive stack when unfocusing from outside
      if (s.diveStack.length > 0) {
        s.diveStack = [];
        if (rootLayoutRef.current) {
          layoutRef.current = rootLayoutRef.current.layout;
          layoutEdgesRef.current = rootLayoutRef.current.edges;
          s.drifts = rootLayoutRef.current.layout.map(() => ({
            ph: Math.random() * Math.PI * 2,
            ax: 4 + Math.random() * 6,
            ay: 4 + Math.random() * 6,
            fx: 0.2 + Math.random() * 0.3,
            fy: 0.2 + Math.random() * 0.3,
          }));
        }
      }
      s.camTarget.x = 0;
      s.camTarget.y = getDefaultCamY(s.W || window.innerWidth, s.H || window.innerHeight);
      s.camTarget.z = getDefaultZoom(s.W || window.innerWidth);
    }
  }, [focusedNodeId]);

  // Canvas resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resize = () => {
      const s = stateRef.current;
      s.W = canvas.clientWidth;
      s.H = canvas.clientHeight;
      const d = window.devicePixelRatio || 1;
      canvas.width = s.W * d;
      canvas.height = s.H * d;
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.setTransform(d, 0, 0, d, 0, 0);
      // Update zoom targets for new size
      if (!focusedRef.current && s.diveStack.length === 0) {
        s.camTarget.z = getDefaultZoom(s.W);
        s.camTarget.y = getDefaultCamY(s.W, s.H);
      } else if (focusedRef.current) {
        s.camTarget.z = getFocusZoom(s.W);
      }
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // The main animation loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const accent = (): [number, number, number] => {
      return dark ? [45, 212, 191] : [15, 118, 110];
    };

    const animate = () => {
      const s = stateRef.current;
      const lnodes = layoutRef.current;
      const ledges = layoutEdgesRef.current;
      const focused = focusedRef.current;
      s.time += 0.016;

      // Camera lerp
      s.cam.x += (s.camTarget.x - s.cam.x) * CAM_SPEED;
      s.cam.y += (s.camTarget.y - s.cam.y) * CAM_SPEED;
      s.cam.z += (s.camTarget.z - s.cam.z) * CAM_SPEED;

      // Child expand
      if (focused) s.childExpandT = Math.min(1, s.childExpandT + 0.03);
      else s.childExpandT = Math.max(0, s.childExpandT - 0.04);

      // Ring crossfade
      if (s.ringFadeT < 1) s.ringFadeT = Math.min(1, s.ringFadeT + 0.04);

      const { W, H, cam, mouse, particles, drifts } = s;
      if (!W || !H) { s.rafId = requestAnimationFrame(animate); return; }

      const toScreen = (wx: number, wy: number) => ({
        x: (wx - cam.x) * cam.z + W / 2,
        y: (wy - cam.y) * cam.z + H / 2,
      });
      const toWorld = (sx: number, sy: number) => ({
        x: (sx - W / 2) / cam.z + cam.x,
        y: (sy - H / 2) / cam.z + cam.y,
      });

      const [ar, ag, ab] = accent();
      const wm = toWorld(mouse.x, mouse.y);

      ctx.clearRect(0, 0, W, H);

      // ── Particles ──
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy;
        if (p.x < -450 || p.x > 450) p.vx *= -1;
        if (p.y < -325 || p.y > 325) p.vy *= -1;
        const sp = toScreen(p.x, p.y);
        const dm = Math.hypot(p.x - wm.x, p.y - wm.y);
        const glow = dm < 120 ? (120 - dm) / 120 * 0.12 : 0;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, (p.r + glow * 3) * cam.z, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ar},${ag},${ab},${p.a + glow})`;
        ctx.fill();
      }

      // ── Edges ──
      for (const [i, j] of ledges) {
        const na = lnodes[i], nb = lnodes[j];
        if (!na || !nb) continue;
        const aw = nodeWorldPos(na, drifts, lnodes, s.time);
        const bw = nodeWorldPos(nb, drifts, lnodes, s.time);
        const a = toScreen(aw.x, aw.y), b = toScreen(bw.x, bw.y);
        const mx = (aw.x + bw.x) / 2, my = (aw.y + bw.y) / 2;
        const dm = Math.hypot(mx - wm.x, my - wm.y);
        const prox = dm < 160 ? (160 - dm) / 160 : 0;
        let fade = 1;
        if (focused) {
          const fi = lnodes.indexOf(focused);
          fade = (i === fi || j === fi) ? 1 : 0.15;
        }
        const alpha = (0.10 + prox * 0.18) * fade;
        const cpx = (a.x + b.x) / 2 + (a.y - b.y) * 0.08;
        const cpy = (a.y + b.y) / 2 - (a.x - b.x) * 0.08;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(cpx, cpy, b.x, b.y);
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${alpha})`;
        ctx.lineWidth = 1 * cam.z; ctx.stroke();
      }

      // ── Nodes ──
      let newHovered: LayoutNode | null = null;
      for (const node of lnodes) {
        const wp = nodeWorldPos(node, drifts, lnodes, s.time);
        const sp = toScreen(wp.x, wp.y);
        const sr = node.r * cam.z;
        const dm = Math.hypot(sp.x - mouse.x, sp.y - mouse.y);
        const isHover = dm < sr + 14 * cam.z && !s.dragging;
        if (isHover && node !== focused) newHovered = node;

        let dim = 1;
        if (focused && focused !== node) dim = 0.2;
        if (focused === node) dim = 1.3;
        const ga = (isHover ? 1 : Math.max(0, 1 - dm / (200 * cam.z)) * 0.25) * dim;

        // Glow
        if (ga > 0.02) {
          const grad = ctx.createRadialGradient(sp.x, sp.y, sr * 0.5, sp.x, sp.y, sr + 28 * cam.z * ga);
          grad.addColorStop(0, `rgba(${ar},${ag},${ab},${0.10 * ga})`);
          grad.addColorStop(1, `rgba(${ar},${ag},${ab},0)`);
          ctx.beginPath(); ctx.arc(sp.x, sp.y, sr + 28 * cam.z * ga, 0, Math.PI * 2);
          ctx.fillStyle = grad; ctx.fill();
        }

        const r = sr + (isHover && !focused ? 3 * cam.z : 0) + (focused === node ? 5 * cam.z : 0);
        ctx.beginPath(); ctx.arc(sp.x, sp.y, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ar},${ag},${ab},${(0.06 + ga * 0.10) * dim})`;
        ctx.fill();
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${(0.22 + ga * 0.35) * dim})`;
        ctx.lineWidth = (focused === node ? 1.8 : 1) * cam.z;
        ctx.stroke();

        // Center dot
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, (2.8 + ga * 1.5) * cam.z, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ar},${ag},${ab},${(0.35 + ga * 0.45) * dim})`;
        ctx.fill();

        // Label
        const fs = ((isHover || focused === node) ? 12 : 10.5) * cam.z;
        ctx.font = `${(isHover || focused === node) ? "600" : "500"} ${fs}px Inter,sans-serif`;
        ctx.fillStyle = `rgba(${ar},${ag},${ab},${(0.35 + ga * 0.55) * dim})`;
        ctx.textAlign = "center";
        ctx.fillText(node.title, sp.x, sp.y + r + 15 * cam.z);
      }
      s.hoveredNode = newHovered;

      // ── Children ──
      let newHoveredChild: ChildNode | null = null;
      if (focused && s.childExpandT > 0.01) {
        const pw = nodeWorldPos(focused, drifts, lnodes, s.time);
        const t = s.childExpandT;
        const ringAlpha = s.ringFadeT;
        const spread = 2.4;
        for (const child of focused.children) {
          const cwx = pw.x + child.dx * spread * t;
          const cwy = pw.y + child.dy * spread * t;
          const cs = toScreen(cwx, cwy);
          const ps = toScreen(pw.x, pw.y);
          const cr = child.r * cam.z * t;

          // Hit test for hover
          const cdm = Math.hypot(cs.x - mouse.x, cs.y - mouse.y);
          const isChildHover = cdm < cr + 10 * cam.z && !s.dragging && t > 0.5;
          if (isChildHover) newHoveredChild = child;

          const fadeAlpha = t * ringAlpha;

          // Edge from parent to child
          ctx.beginPath(); ctx.moveTo(ps.x, ps.y); ctx.lineTo(cs.x, cs.y);
          ctx.strokeStyle = `rgba(${ar},${ag},${ab},${0.15 * fadeAlpha})`;
          ctx.lineWidth = 0.8 * cam.z; ctx.stroke();

          // Child circle
          const childR = cr + (isChildHover ? 3 * cam.z : 0);
          ctx.beginPath(); ctx.arc(cs.x, cs.y, childR, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${ar},${ag},${ab},${(isChildHover ? 0.14 : 0.07) * fadeAlpha})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(${ar},${ag},${ab},${(isChildHover ? 0.5 : 0.28) * fadeAlpha})`;
          ctx.lineWidth = (isChildHover ? 1.2 : 0.7) * cam.z; ctx.stroke();

          // Label
          const cfs = (isChildHover ? 10.5 : 9.5) * cam.z * Math.min(t * 1.5, 1);
          ctx.font = `${isChildHover ? "600" : "500"} ${cfs}px Inter,sans-serif`;
          ctx.fillStyle = `rgba(${ar},${ag},${ab},${(isChildHover ? 0.8 : 0.55) * fadeAlpha})`;
          ctx.textAlign = "center";
          ctx.fillText(child.title, cs.x, cs.y + childR + 12 * cam.z);

          // Child count badge (if has sub-children)
          if (child.childCount > 0 && fadeAlpha > 0.3) {
            const badgeR = 6 * cam.z;
            const bx = cs.x + childR * 0.7;
            const by = cs.y - childR * 0.7;
            ctx.beginPath(); ctx.arc(bx, by, badgeR, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${ar},${ag},${ab},${0.2 * fadeAlpha})`;
            ctx.fill();
            ctx.font = `600 ${7 * cam.z}px Inter,sans-serif`;
            ctx.fillStyle = `rgba(${ar},${ag},${ab},${0.7 * fadeAlpha})`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(String(child.childCount), bx, by);
            ctx.textBaseline = "alphabetic";
          }
        }
      }
      s.hoveredChild = newHoveredChild;

      // Cursor style
      const cv = canvasRef.current;
      if (cv) {
        cv.style.cursor = (s.hoveredNode || s.hoveredChild) && !s.dragging ? "pointer" : s.dragging ? "grabbing" : "default";
      }

      s.rafId = requestAnimationFrame(animate);
    };

    stateRef.current.rafId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(stateRef.current.rafId);
  }, [dark]); // re-create loop when dark changes for accent color

  // Handle canvas click → focus, dive, or back
  const handleCanvasClick = useCallback(
    (sx: number, sy: number) => {
      const s = stateRef.current;
      const lnodes = layoutRef.current;
      const focused = focusedRef.current;
      const toWorld = (sx2: number, sy2: number) => ({
        x: (sx2 - s.W / 2) / s.cam.z + s.cam.x,
        y: (sy2 - s.H / 2) / s.cam.z + s.cam.y,
      });
      const wm = toWorld(sx, sy);

      // Cooldown: ignore clicks within 500ms of a dive
      if (Date.now() - s.lastDiveTime < 500) return;

      // Check if a child node was clicked (only when focused/dived)
      if (focused && s.childExpandT > 0.5) {
        const pw = nodeWorldPos(focused, s.drifts, lnodes, s.time);
        const spread = 2.4;
        for (const child of focused.children) {
          const cwx = pw.x + child.dx * spread * s.childExpandT;
          const cwy = pw.y + child.dy * spread * s.childExpandT;
          if (Math.hypot(cwx - wm.x, cwy - wm.y) < child.r + 12) {
            // Dive into this child — same smooth focus approach as root level
            s.lastDiveTime = Date.now();
            s.diveStack.push(child.id);

            // Save root layout if this is first dive
            if (s.diveStack.length === 1 && rootLayoutRef.current === null) {
              rootLayoutRef.current = { layout: [...layoutRef.current], edges: [...layoutEdgesRef.current] };
            }

            // Build new layout centered on the child's current world position
            // so camera doesn't need to jump
            const { layout: l, layoutEdges: le } = buildDiveLayout(child.id, nodes, edges);
            // Offset new layout to child's current world position
            if (l[0]) {
              l[0].wx = cwx;
              l[0].wy = cwy;
            }
            const newDrifts = l.map(() => ({
              ph: Math.random() * Math.PI * 2,
              ax: 4 + Math.random() * 6,
              ay: 4 + Math.random() * 6,
              fx: 0.2 + Math.random() * 0.3,
              fy: 0.2 + Math.random() * 0.3,
            }));

            // Swap layout immediately but keep camera where it is —
            // the new center node is at the same world position,
            // so the visual transition is just the children collapsing
            // and new children expanding (same as first-level focus).
            layoutRef.current = l;
            layoutEdgesRef.current = le;
            s.drifts = newDrifts;
            s.childExpandT = 0;
            s.ringFadeT = 0;
            s.ringFadeDir = 1;

            // Focus the new center node — camera lerps to it smoothly
            focusedRef.current = l[0] ?? null;
            if (l[0]) {
              s.camTarget = { x: cwx, y: cwy - 20, z: getFocusZoom(s.W || window.innerWidth) };
            }
            s.skipSync = true;
            onNodeFocus(l[0] ? { id: l[0].id, title: l[0].title } : null);
            return;
          }
        }
      }

      // Check if a top-level node was clicked
      let clicked: LayoutNode | null = null;
      for (const n of lnodes) {
        const wp = nodeWorldPos(n, s.drifts, lnodes, s.time);
        if (Math.hypot(wp.x - wm.x, wp.y - wm.y) < n.r + 12) clicked = n;
      }

      if (clicked && clicked.id !== focusedNodeId) {
        s.lastDiveTime = Date.now();
        onNodeFocus(clicked);
      } else if (!clicked) {
        // Clicked empty space
        if (s.diveStack.length > 0) {
          // Back out one level — immediate swap at same position (mirrors dive-in)
          const poppedId = s.diveStack.pop()!;
          s.lastDiveTime = Date.now();

          // Record current center node's world position before swap
          const oldCenter = layoutRef.current[0];
          const oldPos = oldCenter
            ? nodeWorldPos(oldCenter, s.drifts, layoutRef.current, s.time)
            : { x: s.cam.x, y: s.cam.y };

          if (s.diveStack.length > 0) {
            // Still dived — rebuild parent layout
            const parentId = s.diveStack[s.diveStack.length - 1];
            const { layout: l, layoutEdges: le } = buildDiveLayout(parentId, nodes, edges);
            // Position new center at old center's world position — no visual jump
            if (l[0]) {
              l[0].wx = oldPos.x;
              l[0].wy = oldPos.y;
            }
            layoutRef.current = l;
            layoutEdgesRef.current = le;
            s.drifts = l.map(() => ({
              ph: Math.random() * Math.PI * 2,
              ax: 4 + Math.random() * 6,
              ay: 4 + Math.random() * 6,
              fx: 0.2 + Math.random() * 0.3,
              fy: 0.2 + Math.random() * 0.3,
            }));
            s.childExpandT = 0;
            s.ringFadeT = 0;
            focusedRef.current = l[0] ?? null;
            if (l[0]) {
              s.camTarget = { x: l[0].wx, y: l[0].wy - 20, z: getFocusZoom(s.W || window.innerWidth) };
            }
            s.skipSync = true;
            onNodeFocus(l[0] ? { id: l[0].id, title: l[0].title } : null);
          } else {
            // Back to root — restore and re-focus parent featured node
            if (rootLayoutRef.current) {
              layoutRef.current = rootLayoutRef.current.layout;
              layoutEdgesRef.current = rootLayoutRef.current.edges;
              s.drifts = rootLayoutRef.current.layout.map(() => ({
                ph: Math.random() * Math.PI * 2,
                ax: 4 + Math.random() * 6,
                ay: 4 + Math.random() * 6,
                fx: 0.2 + Math.random() * 0.3,
                fy: 0.2 + Math.random() * 0.3,
              }));
              const parentNode = rootLayoutRef.current.layout.find((n) =>
                n.children.some((c) => c.id === poppedId)
              );
              if (parentNode) {
                s.childExpandT = 0;
                s.ringFadeT = 0;
                focusedRef.current = parentNode;
                const wp = nodeWorldPos(parentNode, s.drifts, layoutRef.current, s.time);
                s.camTarget = { x: wp.x, y: wp.y - 20, z: getFocusZoom(s.W || window.innerWidth) };
                s.skipSync = true;
                onNodeFocus({ id: parentNode.id, title: parentNode.title });
              } else {
                focusedRef.current = null;
                s.camTarget = { x: 0, y: getDefaultCamY(s.W || window.innerWidth, s.H || window.innerHeight), z: getDefaultZoom(s.W || window.innerWidth) };
                onNodeFocus(null);
              }
            } else {
              focusedRef.current = null;
              s.camTarget = { x: 0, y: getDefaultCamY(s.W || window.innerWidth, s.H || window.innerHeight), z: getDefaultZoom(s.W || window.innerWidth) };
              onNodeFocus(null);
            }
          }
        } else if (focusedNodeId) {
          // Unfocus at root level
          onNodeFocus(null);
        }
      }
    },
    [focusedNodeId, onNodeFocus, nodes, edges],
  );

  // ── Mouse events ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const s = stateRef.current;

    const onMouseDown = (e: MouseEvent) => {
      s.dragging = true; s.dragDistance = 0;
      s.dragStart = { x: e.clientX, y: e.clientY };
      s.camAtDragStart = { x: s.camTarget.x, y: s.camTarget.y };
    };
    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      s.mouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      if (s.dragging) {
        const dx = e.clientX - s.dragStart.x;
        const dy = e.clientY - s.dragStart.y;
        s.dragDistance = Math.hypot(dx, dy);
        s.camTarget.x = s.camAtDragStart.x - dx / s.cam.z;
        s.camTarget.y = s.camAtDragStart.y - dy / s.cam.z;
      }
    };
    const onMouseUp = (e: MouseEvent) => {
      if (s.dragging && s.dragDistance < 6) {
        const rect = canvas.getBoundingClientRect();
        handleCanvasClick(e.clientX - rect.left, e.clientY - rect.top);
      }
      s.dragging = false;
    };
    const onMouseLeave = () => { s.mouse = { x: -9999, y: -9999 }; };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      s.camTarget.z = Math.max(0.5, Math.min(4, s.camTarget.z * (e.deltaY > 0 ? 0.9 : 1.1)));
    };

    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("mouseleave", onMouseLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      canvas.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      canvas.removeEventListener("mouseleave", onMouseLeave);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [handleCanvasClick]);

  // ── Touch events ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const s = stateRef.current;

    const getTouchDist = (ts: TouchList) =>
      ts.length < 2 ? 0 : Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY);

    const onTouchStart = (e: TouchEvent) => {
      e.preventDefault();
      if (e.touches.length === 1) {
        s.dragging = true; s.pinching = false; s.dragDistance = 0;
        const t = e.touches[0];
        s.dragStart = { x: t.clientX, y: t.clientY };
        s.camAtDragStart = { x: s.camTarget.x, y: s.camTarget.y };
        const r = canvas.getBoundingClientRect();
        s.mouse = { x: t.clientX - r.left, y: t.clientY - r.top };
      } else if (e.touches.length === 2) {
        s.dragging = false; s.pinching = true;
        s.pinchStartDist = getTouchDist(e.touches);
        s.zoomAtPinchStart = s.camTarget.z;
        const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        s.dragStart = { x: cx, y: cy };
        s.camAtDragStart = { x: s.camTarget.x, y: s.camTarget.y };
      }
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      if (s.dragging && e.touches.length === 1) {
        const t = e.touches[0];
        const dx = t.clientX - s.dragStart.x;
        const dy = t.clientY - s.dragStart.y;
        s.dragDistance = Math.hypot(dx, dy);
        s.camTarget.x = s.camAtDragStart.x - dx / s.cam.z;
        s.camTarget.y = s.camAtDragStart.y - dy / s.cam.z;
        const r = canvas.getBoundingClientRect();
        s.mouse = { x: t.clientX - r.left, y: t.clientY - r.top };
      } else if (s.pinching && e.touches.length === 2) {
        const dist = getTouchDist(e.touches);
        s.camTarget.z = Math.max(0.5, Math.min(4, s.zoomAtPinchStart * (dist / s.pinchStartDist)));
        const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        s.camTarget.x = s.camAtDragStart.x - (cx - s.dragStart.x) / s.cam.z;
        s.camTarget.y = s.camAtDragStart.y - (cy - s.dragStart.y) / s.cam.z;
      }
    };
    const onTouchEnd = (e: TouchEvent) => {
      if (s.dragging && s.dragDistance < 12) handleCanvasClick(s.mouse.x, s.mouse.y);
      if (e.touches.length === 0) {
        s.dragging = false; s.pinching = false;
        s.mouse = { x: -9999, y: -9999 };
      } else if (e.touches.length === 1) {
        s.pinching = false; s.dragging = true; s.dragDistance = 0;
        s.dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        s.camAtDragStart = { x: s.camTarget.x, y: s.camTarget.y };
      }
    };

    canvas.addEventListener("touchstart", onTouchStart, { passive: false });
    canvas.addEventListener("touchmove", onTouchMove, { passive: false });
    canvas.addEventListener("touchend", onTouchEnd);

    return () => {
      canvas.removeEventListener("touchstart", onTouchStart);
      canvas.removeEventListener("touchmove", onTouchMove);
      canvas.removeEventListener("touchend", onTouchEnd);
    };
  }, [handleCanvasClick]);

  return <canvas ref={canvasRef} id="mindscape" className="absolute inset-0 w-full h-full" />;
}

/* ── helper: node world pos with drift ── */
function nodeWorldPos(
  n: LayoutNode,
  drifts: Drift[],
  lnodes: LayoutNode[],
  time: number,
): { x: number; y: number } {
  const i = lnodes.indexOf(n);
  const d = drifts[i >= 0 ? i : 0];
  if (!d) return { x: n.wx, y: n.wy };
  return {
    x: n.wx + Math.sin(time * d.fx + d.ph) * d.ax,
    y: n.wy + Math.cos(time * d.fy + d.ph * 1.3) * d.ay,
  };
}
