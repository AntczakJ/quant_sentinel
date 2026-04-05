/**
 * drawings/renderFns.ts — Pure canvas render functions, one per drawing tool.
 *
 * Every function receives pixel-space points, the drawing style, and chart
 * dimensions.  They draw directly on a CanvasRenderingContext2D.
 *
 * Optimizations:
 *  - Every render function is wrapped in ctx.save() / ctx.restore() to avoid
 *    state leaks between drawings (no manual setLineDash cleanup needed).
 *  - Freehand path uses quadratic bezier smoothing for professional curves.
 *  - Selection handles are circles with subtle glow instead of squares.
 *  - Position tool shows Risk:Reward ratio.
 */

import type { DrawingStyle, FibLevel } from './types';
import { DEFAULT_FIB_LEVELS } from './types';

interface Pt { x: number; y: number }

/* ── helpers ─────────────────────────────────────────────────────────────── */

function applyLineStyle(ctx: CanvasRenderingContext2D, s: DrawingStyle) {
  ctx.strokeStyle = s.color;
  ctx.lineWidth = s.lineWidth;
  switch (s.lineStyle) {
    case 'dashed': ctx.setLineDash([6, 4]); break;
    case 'dotted': ctx.setLineDash([2, 3]); break;
    default:       ctx.setLineDash([]); break;
  }
}

function drawLine(ctx: CanvasRenderingContext2D, a: Pt, b: Pt) {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

/** Extend line through a→b to the full chart bounding box. */
function extendLine(a: Pt, b: Pt, w: number, h: number, mode: 'both' | 'right'): [Pt, Pt] {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) {return [a, b];}

  // Find t values where the line intersects viewport edges
  const tValues: number[] = [];
  if (dx !== 0) {
    tValues.push(-a.x / dx);       // left edge
    tValues.push((w - a.x) / dx);  // right edge
  }
  if (dy !== 0) {
    tValues.push(-a.y / dy);       // top edge
    tValues.push((h - a.y) / dy);  // bottom edge
  }

  // Keep only intersections that land within (or near) the viewport
  const validT: number[] = [];
  for (const t of tValues) {
    const px = a.x + t * dx;
    const py = a.y + t * dy;
    if (px >= -10 && px <= w + 10 && py >= -10 && py <= h + 10) {
      validT.push(t);
    }
  }

  if (validT.length === 0) {return [a, b];}

  let tMin = Math.min(...validT);
  const tMax = Math.max(...validT);

  if (mode === 'right') {tMin = 0;} // ray — start at point A, extend only forward

  return [
    { x: a.x + tMin * dx, y: a.y + tMin * dy },
    { x: a.x + tMax * dx, y: a.y + tMax * dy },
  ];
}

/* ── Tool renderers ──────────────────────────────────────────────────────── */

export function renderTrendLine(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle) {
  if (pts.length < 2) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  drawLine(ctx, pts[0], pts[1]);
  ctx.restore();
}

export function renderRay(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, w: number, h: number) {
  if (pts.length < 2) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  const [, end] = extendLine(pts[0], pts[1], w, h, 'right');
  drawLine(ctx, pts[0], end);
  ctx.restore();
}

export function renderExtendedLine(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, w: number, h: number) {
  if (pts.length < 2) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  const [start, end] = extendLine(pts[0], pts[1], w, h, 'both');
  drawLine(ctx, start, end);
  ctx.restore();
}

export function renderHLine(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, w: number) {
  if (pts.length < 1) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  drawLine(ctx, { x: 0, y: pts[0].y }, { x: w, y: pts[0].y });

  // Price label (right-aligned, with background pill)
  if (s.text) {
    ctx.font = '10px monospace';
    const m = ctx.measureText(s.text);
    const lx = w - m.width - 12;
    const ly = pts[0].y;

    ctx.fillStyle = s.color;
    ctx.globalAlpha = 0.12;
    ctx.beginPath();
    ctx.roundRect(lx - 2, ly - 11, m.width + 10, 14, 3);
    ctx.fill();

    ctx.globalAlpha = 1;
    ctx.fillStyle = s.color;
    ctx.textAlign = 'right';
    ctx.fillText(s.text, w - 6, ly - 1);
    ctx.textAlign = 'left';
  }
  ctx.restore();
}

export function renderVLine(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, h: number) {
  if (pts.length < 1) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  drawLine(ctx, { x: pts[0].x, y: 0 }, { x: pts[0].x, y: h });
  ctx.restore();
}

export function renderChannel(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, _w: number, _h: number) {
  if (pts.length < 2) {return;}
  ctx.save();
  applyLineStyle(ctx, s);

  // Base line
  drawLine(ctx, pts[0], pts[1]);

  if (pts.length >= 3) {
    // Parallel line offset
    const dx = pts[1].x - pts[0].x;
    const dy = pts[1].y - pts[0].y;
    const ox = pts[2].x - pts[0].x;
    const oy = pts[2].y - pts[0].y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    const dist = ox * nx + oy * ny;
    const p3: Pt = { x: pts[0].x + nx * dist, y: pts[0].y + ny * dist };
    const p4: Pt = { x: pts[1].x + nx * dist, y: pts[1].y + ny * dist };
    drawLine(ctx, p3, p4);

    // Fill between
    ctx.fillStyle = s.fillColor;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    ctx.lineTo(pts[1].x, pts[1].y);
    ctx.lineTo(p4.x, p4.y);
    ctx.lineTo(p3.x, p3.y);
    ctx.closePath();
    ctx.fill();

    // Middle line (dashed)
    const mid1: Pt = { x: (pts[0].x + p3.x) / 2, y: (pts[0].y + p3.y) / 2 };
    const mid2: Pt = { x: (pts[1].x + p4.x) / 2, y: (pts[1].y + p4.y) / 2 };
    ctx.setLineDash([4, 4]);
    ctx.globalAlpha = 0.5;
    drawLine(ctx, mid1, mid2);
  }
  ctx.restore();
}

export function renderFib(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, w: number) {
  if (pts.length < 2) {return;}
  ctx.save();

  const top = Math.min(pts[0].y, pts[1].y);
  const bot = Math.max(pts[0].y, pts[1].y);
  const range = bot - top;
  const leftX = Math.min(pts[0].x, pts[1].x);

  const levels: FibLevel[] = s.fibLevels ?? DEFAULT_FIB_LEVELS;
  const visibleLevels = levels.filter(l => l.visible);

  for (let i = 0; i < visibleLevels.length; i++) {
    const { level, color } = visibleLevels[i];
    const y = bot - level * range;

    // Fill between this level and next visible
    if (i < visibleLevels.length - 1) {
      const nextLevel = visibleLevels[i + 1];
      const nextY = bot - nextLevel.level * range;
      ctx.fillStyle = color.replace(/[\d.]+\)$/, '0.06)');
      ctx.fillRect(leftX, Math.min(y, nextY), w - leftX, Math.abs(nextY - y));
    }

    // Level line
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(leftX, y);
    ctx.lineTo(w, y);
    ctx.stroke();

    // Label with background
    ctx.font = 'bold 9px monospace';
    const label = `${(level * 100).toFixed(1)}%`;
    const tm = ctx.measureText(label);
    ctx.fillStyle = color.replace(/[\d.]+\)$/, '0.12)');
    ctx.beginPath();
    ctx.roundRect(leftX + 2, y - 12, tm.width + 6, 12, 2);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(label, leftX + 5, y - 3);
  }
  ctx.restore();
}

export function renderRect(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle) {
  if (pts.length < 2) {return;}
  ctx.save();

  const x = Math.min(pts[0].x, pts[1].x);
  const y = Math.min(pts[0].y, pts[1].y);
  const w = Math.abs(pts[1].x - pts[0].x);
  const h = Math.abs(pts[1].y - pts[0].y);

  ctx.fillStyle = s.fillColor;
  ctx.fillRect(x, y, w, h);

  applyLineStyle(ctx, s);
  ctx.strokeRect(x, y, w, h);
  ctx.restore();
}

export function renderPath(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle) {
  if (pts.length < 2) {return;}
  ctx.save();
  applyLineStyle(ctx, s);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);

  if (pts.length === 2) {
    ctx.lineTo(pts[1].x, pts[1].y);
  } else {
    // Smooth curve using quadratic bezier through midpoints
    for (let i = 0; i < pts.length - 1; i++) {
      const midX = (pts[i].x + pts[i + 1].x) / 2;
      const midY = (pts[i].y + pts[i + 1].y) / 2;
      ctx.quadraticCurveTo(pts[i].x, pts[i].y, midX, midY);
    }
    // Connect to the last point
    const last = pts[pts.length - 1];
    ctx.lineTo(last.x, last.y);
  }

  ctx.stroke();
  ctx.restore();
}

export function renderText(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle) {
  if (pts.length < 1 || !s.text) {return;}
  ctx.save();

  const text = s.text;
  ctx.font = `bold ${s.fontSize}px 'Trebuchet MS', sans-serif`;
  const m = ctx.measureText(text);
  const px = pts[0].x;
  const py = pts[0].y;

  // Background pill
  ctx.fillStyle = 'rgba(19,23,34,0.85)';
  ctx.shadowColor = 'rgba(0,0,0,0.3)';
  ctx.shadowBlur = 4;
  ctx.beginPath();
  ctx.roundRect(px - 4, py - s.fontSize - 3, m.width + 10, s.fontSize + 10, 4);
  ctx.fill();

  // Text
  ctx.shadowBlur = 0;
  ctx.fillStyle = s.color;
  ctx.fillText(text, px + 1, py);
  ctx.restore();
}

export function renderMeasure(ctx: CanvasRenderingContext2D, pts: Pt[], s: DrawingStyle, priceA?: number, priceB?: number) {
  if (pts.length < 2) {return;}
  ctx.save();

  // Rect
  renderRect(ctx, pts, { ...s, fillColor: 'rgba(41,98,255,0.08)', color: 'rgba(41,98,255,0.5)' });

  // Info label
  if (priceA !== undefined && priceB !== undefined) {
    const diff = priceB - priceA;
    const pct = priceA !== 0 ? ((diff / priceA) * 100).toFixed(2) : '0';
    const label = `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}  (${pct}%)`;

    const cx = (pts[0].x + pts[1].x) / 2;
    const cy = (pts[0].y + pts[1].y) / 2;

    ctx.font = 'bold 11px monospace';
    const m = ctx.measureText(label);

    // Background
    ctx.fillStyle = 'rgba(19,23,34,0.9)';
    ctx.shadowColor = 'rgba(0,0,0,0.3)';
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.roundRect(cx - m.width / 2 - 8, cy - 12, m.width + 16, 24, 5);
    ctx.fill();

    // Text
    ctx.shadowBlur = 0;
    ctx.fillStyle = diff >= 0 ? '#26a69a' : '#ef5350';
    ctx.textAlign = 'center';
    ctx.fillText(label, cx, cy + 4);
    ctx.textAlign = 'left';
  }
  ctx.restore();
}

export function renderPosition(
  ctx: CanvasRenderingContext2D, pts: Pt[], _s: DrawingStyle,
  direction: 'long' | 'short', _w: number,
  priceA?: number, priceB?: number,
) {
  if (pts.length < 2 || priceA === undefined || priceB === undefined) {return;}
  ctx.save();

  const entryY = pts[0].y;
  const targetY = pts[1].y;
  const entryPrice = priceA;
  const targetPrice = priceB;

  const diff = targetPrice - entryPrice;
  const slPrice = entryPrice - diff;
  const slY = entryY + (entryY - targetY);

  const tpColor = 'rgba(38,166,154,';
  const slColor = 'rgba(239,83,80,';

  const x1 = pts[0].x;
  const x2 = x1 + 220; // fixed width

  // TP zone
  ctx.fillStyle = tpColor + '0.10)';
  ctx.fillRect(x1, Math.min(entryY, targetY), x2 - x1, Math.abs(targetY - entryY));
  ctx.strokeStyle = tpColor + '0.5)';
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.strokeRect(x1, Math.min(entryY, targetY), x2 - x1, Math.abs(targetY - entryY));

  // SL zone
  ctx.fillStyle = slColor + '0.10)';
  ctx.fillRect(x1, Math.min(entryY, slY), x2 - x1, Math.abs(slY - entryY));
  ctx.strokeStyle = slColor + '0.5)';
  ctx.strokeRect(x1, Math.min(entryY, slY), x2 - x1, Math.abs(slY - entryY));

  // Entry line
  ctx.strokeStyle = '#2962ff';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x1, entryY);
  ctx.lineTo(x2, entryY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Labels
  ctx.font = 'bold 10px monospace';
  const tpPips = Math.abs(targetPrice - entryPrice).toFixed(1);
  const slPips = Math.abs(slPrice - entryPrice).toFixed(1);
  const dirLabel = direction === 'long' ? 'LONG' : 'SHORT';

  // R:R ratio
  const slDist = Math.abs(slPrice - entryPrice);
  const tpDist = Math.abs(targetPrice - entryPrice);
  const rr = slDist > 0 ? (tpDist / slDist).toFixed(1) : '∞';

  ctx.fillStyle = tpColor + '0.9)';
  ctx.fillText(`TP ${targetPrice.toFixed(2)} (+${tpPips})`, x1 + 5, Math.min(entryY, targetY) + 14);
  ctx.fillStyle = slColor + '0.9)';
  ctx.fillText(`SL ${slPrice.toFixed(2)} (-${slPips})`, x1 + 5, Math.max(entryY, slY) - 5);
  ctx.fillStyle = '#2962ff';
  ctx.fillText(`${dirLabel} ${entryPrice.toFixed(2)}`, x1 + 5, entryY - 5);

  // R:R badge
  ctx.fillStyle = 'rgba(19,23,34,0.85)';
  const rrLabel = `R:R  1:${rr}`;
  const rrM = ctx.measureText(rrLabel);
  ctx.beginPath();
  ctx.roundRect(x2 - rrM.width - 16, entryY - 11, rrM.width + 12, 14, 3);
  ctx.fill();
  ctx.fillStyle = '#e2e8f0';
  ctx.textAlign = 'right';
  ctx.fillText(rrLabel, x2 - 8, entryY);
  ctx.textAlign = 'left';

  ctx.restore();
}

/** Selection handles: circles with glow at anchor points. */
export function renderHandles(ctx: CanvasRenderingContext2D, pts: Pt[], color: string) {
  ctx.save();
  const R = 5;

  for (const p of pts) {
    // Glow
    ctx.shadowColor = color;
    ctx.shadowBlur = 8;

    // Filled circle
    ctx.beginPath();
    ctx.arc(p.x, p.y, R, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    // White border
    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.arc(p.x, p.y, R, 0, Math.PI * 2);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.stroke();
  }

  ctx.restore();
}
