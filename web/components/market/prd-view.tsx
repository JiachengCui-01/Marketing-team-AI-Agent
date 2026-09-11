"use client";

import { type MarketPrd } from "@/lib/api";
import { Modal } from "@/components/modal";
import { useI18n } from "@/lib/i18n";
import { EvidenceChip } from "@/components/market/shared";

/** The product definition, read-only.
 *
 * Placeholders are rendered deliberately loudly. `[待确认 尺寸]` is not a blank to
 * be skimmed past — it is the document saying no vendor data exists for that field
 * and somebody has to go and measure it.
 */
export function PrdView({ prd, onClose }: { prd: MarketPrd; onClose: () => void }) {
  const { t } = useI18n();
  const doc = prd.prd ?? {};

  return (
    <Modal title={`${t.prdTitle} · ${prd.title}`} onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        {doc.opportunity ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
            <span className="bi-chip">{doc.opportunity.anchor_asin}</span>
            <span>{t.scProductScore} {doc.opportunity.product_score}</span>
            <span>{t.scConfidence} {doc.opportunity.score_confidence}</span>
            {doc.category ? <span>{doc.category.label}</span> : null}
          </div>
        ) : null}

        <Field label={t.prdPositioning} value={doc.positioning} />
        <Field label={t.prdTargetUser} value={doc.target_user} />
        <Field label={t.prdScenario} value={doc.use_scenario} />

        <Claims label={t.prdBasis} items={doc.opportunity_basis} />

        <Field label={t.prdPriceBand} value={doc.target_price_band} hint={doc.price_rationale} />

        <SpecList label={t.prdDimensions} rows={doc.dimensions} nameKey="name" valueKey="value" />
        <SpecList label={t.prdMaterials} rows={doc.materials} nameKey="part" valueKey="material" />
        <Field label={t.prdLoad} value={doc.load_capacity} hint={doc.structure_notes} />

        {doc.assembly ? (
          <Group label={t.prdAssembly}>
            <Placeholder value={doc.assembly.parts_count} />
            <Placeholder value={doc.assembly.est_minutes} />
            {doc.assembly.notes ? (
              <p className="text-xs text-fg-muted">{doc.assembly.notes}</p>
            ) : null}
          </Group>
        ) : null}

        {doc.packaging ? (
          <Group label={t.prdPackaging}>
            <Placeholder value={doc.packaging.carton_plan} />
            {doc.packaging.fragile_points?.length ? (
              <div className="text-xs">
                <span className="text-fg-muted">{t.prdFragile}: </span>
                {doc.packaging.fragile_points.join("、")}
                {doc.packaging.evidence_ids?.length ? (
                  <EvidenceChip ids={doc.packaging.evidence_ids} />
                ) : null}
              </div>
            ) : null}
          </Group>
        ) : null}

        {doc.differentiators?.length ? (
          <Group label={t.prdDifferentiators}>
            <ul className="space-y-1">
              {doc.differentiators.map((item: any, i: number) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span>{item.claim}</span>
                  <span className={`bi-chip ${
                    item.backing === "to_validate" ? "bi-chip-estimated" : "bi-chip-observed"}`}>
                    {item.backing}
                  </span>
                  {item.evidence_ids?.length ? <EvidenceChip ids={item.evidence_ids} /> : null}
                </li>
              ))}
            </ul>
          </Group>
        ) : null}

        {doc.economics ? (
          <Group label={t.prdEconomics}>
            <Placeholder value={doc.economics.target_landed_cost_range} />
            <Placeholder value={doc.economics.target_gross_margin_range} />
          </Group>
        ) : null}

        {prd.assumptions?.length ? (
          <Group label={t.prdAssumptions}>
            <ul className="space-y-0.5">
              {prd.assumptions.map((item, i) => (
                <li key={i} className="text-xs text-warn">{item}</li>
              ))}
            </ul>
          </Group>
        ) : null}

        <Claims label={t.prdRisks} items={doc.risks} textKey="risk" />

        {doc.validation_plan?.length ? (
          <Group label={t.prdValidation}>
            <ol className="list-decimal space-y-1 pl-5">
              {doc.validation_plan.map((row: any, i: number) => (
                <li key={i} className="text-xs">
                  {row.question}
                  {row.method ? <span className="text-fg-subtle"> · {row.method}</span> : null}
                  {row.generated ? (
                    <span className="ml-1 text-[10px] text-fg-subtle">(auto)</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </Group>
        ) : null}

        {prd.notes?.length ? (
          <Group label={t.prdGaps}>
            <ul className="space-y-0.5">
              {prd.notes.map((note, i) => (
                <li key={i} className="text-xs text-fg-muted">{note}</li>
              ))}
            </ul>
          </Group>
        ) : null}
      </div>
    </Modal>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium text-fg-muted">{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Field({ label, value, hint }: { label: string; value?: string; hint?: string }) {
  if (!value) return null;
  return (
    <Group label={label}>
      <Placeholder value={value} />
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </Group>
  );
}

/** `[待确认 …]` is rendered as a warning, not as text. It means no vendor data
 * exists for that field and the number has to be measured, not guessed. */
function Placeholder({ value }: { value?: string }) {
  if (!value) return null;
  const pending = value.startsWith("[待确认") || value.startsWith("[confirm");
  return <p className={pending ? "bi-placeholder text-xs" : "text-sm"}>{value}</p>;
}

function SpecList({
  label,
  rows,
  nameKey,
  valueKey,
}: {
  label: string;
  rows?: any[];
  nameKey: string;
  valueKey: string;
}) {
  const { t } = useI18n();
  if (!rows?.length) return null;
  return (
    <Group label={label}>
      <ul className="space-y-0.5">
        {rows.map((row, i) => (
          <li key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-fg-muted">{row[nameKey]}</span>
            <Placeholder value={row[valueKey]} />
            {row.source === "competitor_observed" ? (
              <span className="bi-chip bi-chip-observed">{t.prdCompetitorRef}</span>
            ) : null}
            {row.evidence_ids?.length ? <EvidenceChip ids={row.evidence_ids} /> : null}
          </li>
        ))}
      </ul>
    </Group>
  );
}

function Claims({
  label,
  items,
  textKey = "claim",
}: {
  label: string;
  items?: any[];
  textKey?: string;
}) {
  if (!items?.length) return null;
  return (
    <Group label={label}>
      <ul className="space-y-0.5">
        {items.map((item, i) => (
          <li key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
            <span>{item[textKey]}</span>
            {item.evidence_ids?.length ? <EvidenceChip ids={item.evidence_ids} /> : null}
          </li>
        ))}
      </ul>
    </Group>
  );
}
