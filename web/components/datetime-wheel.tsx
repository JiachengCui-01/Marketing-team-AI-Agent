"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

const ITEM_H = 36;
const VISIBLE = 5; // odd number → clear center row
const PAD = Math.floor(VISIBLE / 2);
const MIN_STEP = 5; // minute granularity

type Opt = { value: number; label: string };

/** A single scroll-snap wheel column with a 3D tilt + fade for a lively feel. */
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
      node.style.transform = `perspective(600px) rotateX(${Math.max(-60, Math.min(60, d * -22))}deg) scale(${Math.max(0.62, 1 - ad * 0.16)})`;
      node.style.opacity = String(Math.max(0.2, 1 - ad * 0.34));
    });
  }, []);

  // Keep the wheel aligned to the selected value when it changes externally.
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

/** Parse a "YYYY-MM-DDTHH:MM" (or Date-parseable) string; null if invalid. */
function parseValue(v: string | null | undefined): Date | null {
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Future-only date + time wheel. Emits a local "YYYY-MM-DDTHH:MM" string via onChange.
 * Past days/hours/minutes are never rendered, so a past time cannot be selected.
 */
export function DateTimeWheel({
  value,
  onChange,
  zh = true,
}: {
  value: string | null;
  onChange: (iso: string) => void;
  zh?: boolean;
}) {
  const now = useMemo(() => new Date(), []);
  const today0 = startOfDay(now);

  const days = useMemo(() => {
    const list: Date[] = [];
    for (let i = 0; i < 60; i++) {
      const d = new Date(today0);
      d.setDate(d.getDate() + i);
      list.push(d);
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today0.getTime()]);

  const selected = parseValue(value) ?? nextValidNow(now);
  const selDay0 = startOfDay(selected);
  let dayIdx = days.findIndex((d) => d.getTime() === selDay0.getTime());
  if (dayIdx < 0) dayIdx = 0;
  const isToday = dayIdx === 0;

  const minHour = isToday ? now.getHours() : 0;
  const hours: Opt[] = [];
  for (let h = minHour; h <= 23; h++) hours.push({ value: h, label: pad2(h) });

  let selHour = selected.getHours();
  if (selHour < minHour) selHour = minHour;

  const minMinute = isToday && selHour === now.getHours() ? ceilStep(now.getMinutes() + 1) : 0;
  const minutes: Opt[] = [];
  for (let m = minMinute; m <= 59; m += MIN_STEP) minutes.push({ value: m, label: pad2(m) });
  if (minutes.length === 0) minutes.push({ value: 0, label: "00" }); // hour fully passed guard

  let selMinute = ceilStep(selected.getMinutes());
  if (!minutes.some((o) => o.value === selMinute)) selMinute = minutes[0].value;

  const dayOpts: Opt[] = days.map((d, i) => ({
    value: i,
    label:
      i === 0
        ? zh ? "今天" : "Today"
        : i === 1
          ? zh ? "明天" : "Tomorrow"
          : zh
            ? `${d.getMonth() + 1}月${d.getDate()}日 周${"日一二三四五六"[d.getDay()]}`
            : d.toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" }),
  }));

  const emit = useCallback(
    (di: number, h: number, m: number) => {
      const d = new Date(days[di] ?? today0);
      d.setHours(h, m, 0, 0);
      // Guard: never emit a past time.
      const floor = nextValidNow(new Date());
      const safe = d.getTime() < floor.getTime() ? floor : d;
      onChange(
        `${safe.getFullYear()}-${pad2(safe.getMonth() + 1)}-${pad2(safe.getDate())}T${pad2(safe.getHours())}:${pad2(safe.getMinutes())}`,
      );
    },
    [days, today0, onChange],
  );

  // Emit the default (soonest valid) selection when opened empty, so a user who
  // doesn't scroll still gets a valid future time.
  const seededRef = useRef(false);
  useEffect(() => {
    if (!value && !seededRef.current) {
      seededRef.current = true;
      emit(dayIdx, selHour, selMinute);
    }
  }, [value, emit, dayIdx, selHour, selMinute]);

  return (
    <div className="relative flex items-stretch justify-center gap-1 rounded-xl border border-border bg-bg-subtle px-2 py-1">
      {/* center selection band */}
      <div
        className="pointer-events-none absolute left-2 right-2 rounded-lg bg-accent/10 border-y border-accent/30"
        style={{ top: ITEM_H * PAD + 1, height: ITEM_H - 2 }}
        aria-hidden
      />
      <Wheel options={dayOpts} value={dayIdx} onChange={(v) => emit(v, selHour, selMinute)} width={140} />
      <Wheel options={hours} value={selHour} onChange={(v) => emit(dayIdx, v, selMinute)} width={56} />
      <div className="flex items-center text-fg-muted text-sm" aria-hidden>
        :
      </div>
      <Wheel options={minutes} value={selMinute} onChange={(v) => emit(dayIdx, selHour, v)} width={56} />
    </div>
  );
}

function ceilStep(m: number): number {
  return Math.min(55, Math.ceil(m / MIN_STEP) * MIN_STEP);
}

function nextValidNow(now: Date): Date {
  const d = new Date(now);
  const m = ceilStep(now.getMinutes() + 1);
  if (m >= 60) {
    d.setHours(d.getHours() + 1, 0, 0, 0);
  } else {
    d.setMinutes(m, 0, 0);
  }
  return d;
}
