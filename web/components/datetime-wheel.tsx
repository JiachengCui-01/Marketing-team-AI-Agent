"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

const ITEM_H = 34;
const VISIBLE = 5; // odd number → clear center row
const PAD = Math.floor(VISIBLE / 2);
const MIN_STEP = 5; // minute granularity

type Opt = { value: number; label: string };

function Wheel({
  options,
  value,
  onChange,
  width,
}: {
  options: Opt[];
  value: number;
  onChange: (v: number) => void;
  width: number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const settleRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  const index = Math.max(0, options.findIndex((o) => o.value === value));

  const paint = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const raw = el.scrollTop / ITEM_H;
    const items = el.querySelectorAll<HTMLElement>("[data-wheel-item]");
    items.forEach((node, i) => {
      const d = i - raw;
      const ad = Math.abs(d);
      node.style.transform = `perspective(560px) rotateX(${Math.max(-62, Math.min(62, d * -24))}deg) scale(${Math.max(0.6, 1 - ad * 0.16)})`;
      node.style.opacity = String(Math.max(0.18, 1 - ad * 0.36));
    });
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const target = index * ITEM_H;
    if (Math.abs(el.scrollTop - target) > 1) el.scrollTop = target;
    paint();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, options.length]);

  const onScroll = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(paint);
    if (settleRef.current) window.clearTimeout(settleRef.current);
    settleRef.current = window.setTimeout(() => {
      const el = ref.current;
      if (!el) return;
      const nearest = Math.max(0, Math.min(options.length - 1, Math.round(el.scrollTop / ITEM_H)));
      const opt = options[nearest];
      if (opt && opt.value !== value) onChange(opt.value);
    }, 110);
  }, [options, value, onChange, paint]);

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      className="dtw-wheel relative overflow-y-auto no-scrollbar"
      style={{ height: ITEM_H * VISIBLE, width, scrollSnapType: "y mandatory" }}
    >
      <div style={{ height: ITEM_H * PAD }} aria-hidden />
      {options.map((o) => (
        <div
          key={o.value}
          data-wheel-item
          onClick={() => onChange(o.value)}
          className="flex items-center justify-center text-sm text-fg cursor-pointer select-none"
          style={{ height: ITEM_H, scrollSnapAlign: "center", transition: "transform 60ms linear" }}
        >
          {o.label}
        </div>
      ))}
      <div style={{ height: ITEM_H * PAD }} aria-hidden />
    </div>
  );
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function pad2(n: number): string {
  return String(n).padStart(2, "0");
}
function parseValue(v: string | Date | null | undefined): Date | null {
  if (!v) return null;
  const d = v instanceof Date ? v : new Date(v);
  return isNaN(d.getTime()) ? null : d;
}
function ceilStep(m: number): number {
  return Math.min(55, Math.ceil(m / MIN_STEP) * MIN_STEP);
}
function nextValidFrom(base: Date): Date {
  const d = new Date(base);
  d.setSeconds(0, 0);
  // Round up to the next 5-min boundary; setMinutes(>=60) rolls into the next hour.
  d.setMinutes(Math.ceil((base.getMinutes() + 1) / MIN_STEP) * MIN_STEP);
  return d;
}

/**
 * Future-only date + time wheel. Emits a local "YYYY-MM-DDTHH:MM" string. Nothing
 * before ``min`` (default = soonest valid time from now) is rendered/selectable, so
 * the end picker can be constrained to after the start.
 */
export function DateTimeWheel({
  value,
  onChange,
  zh = true,
  min,
}: {
  value: string | null;
  onChange: (iso: string) => void;
  zh?: boolean;
  min?: string | Date;
}) {
  const floor = useMemo(() => parseValue(min) ?? nextValidFrom(new Date()), [min]);
  const floorDay0 = startOfDay(floor);

  const days = useMemo(() => {
    const list: Date[] = [];
    for (let i = 0; i < 60; i++) {
      const d = new Date(floorDay0);
      d.setDate(d.getDate() + i);
      list.push(d);
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [floorDay0.getTime()]);

  const selected = parseValue(value) ?? floor;
  const selDay0 = startOfDay(selected);
  let dayIdx = days.findIndex((d) => d.getTime() === selDay0.getTime());
  if (dayIdx < 0) dayIdx = 0;
  const onFloorDay = dayIdx === 0;

  const minHour = onFloorDay ? floor.getHours() : 0;
  const hours: Opt[] = [];
  for (let h = minHour; h <= 23; h++) hours.push({ value: h, label: pad2(h) });
  let selHour = selected.getHours();
  if (selHour < minHour) selHour = minHour;

  const minMinute = onFloorDay && selHour === floor.getHours() ? ceilStep(floor.getMinutes()) : 0;
  const minutes: Opt[] = [];
  for (let m = minMinute; m <= 59; m += MIN_STEP) minutes.push({ value: m, label: pad2(m) });
  if (minutes.length === 0) minutes.push({ value: 0, label: "00" });
  let selMinute = ceilStep(selected.getMinutes());
  if (!minutes.some((o) => o.value === selMinute)) selMinute = minutes[0].value;

  const dayOpts: Opt[] = days.map((d, i) => ({
    value: i,
    label:
      startOfDay(new Date()).getTime() === d.getTime()
        ? zh ? "今天" : "Today"
        : startOfDay(new Date(Date.now() + 86400000)).getTime() === d.getTime()
          ? zh ? "明天" : "Tomorrow"
          : zh
            ? `${d.getMonth() + 1}月${d.getDate()}日 周${"日一二三四五六"[d.getDay()]}`
            : d.toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" }),
  }));

  const emit = useCallback(
    (di: number, h: number, m: number) => {
      const d = new Date(days[di] ?? floorDay0);
      d.setHours(h, m, 0, 0);
      const safe = d.getTime() < floor.getTime() ? floor : d;
      onChange(
        `${safe.getFullYear()}-${pad2(safe.getMonth() + 1)}-${pad2(safe.getDate())}T${pad2(safe.getHours())}:${pad2(safe.getMinutes())}`,
      );
    },
    [days, floorDay0, floor, onChange],
  );

  const seededRef = useRef(false);
  useEffect(() => {
    if (!value && !seededRef.current) {
      seededRef.current = true;
      emit(dayIdx, selHour, selMinute);
    }
  }, [value, emit, dayIdx, selHour, selMinute]);

  return (
    <div className="flex justify-center">
      <div className="dtw-shell relative inline-flex items-stretch gap-1 rounded-xl border border-border bg-bg-subtle px-2 py-1">
        {/* liquid-glass selection band, just wide enough for the wheels. The +5 top
            offset absorbs the shell's 4px top padding so the band centers on the row. */}
        <div
          className="dtw-band pointer-events-none absolute inset-x-2 rounded-lg"
          style={{ top: ITEM_H * PAD + 5, height: ITEM_H - 2 }}
          aria-hidden
        />
        <Wheel options={dayOpts} value={dayIdx} onChange={(v) => emit(v, selHour, selMinute)} width={132} />
        <Wheel options={hours} value={selHour} onChange={(v) => emit(dayIdx, v, selMinute)} width={50} />
        <div className="flex items-center text-fg-muted text-sm" aria-hidden>
          :
        </div>
        <Wheel options={minutes} value={selMinute} onChange={(v) => emit(dayIdx, selHour, v)} width={50} />
      </div>
    </div>
  );
}
