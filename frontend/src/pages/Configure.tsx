import { useEffect, useMemo, useState } from "react";
import { api, type Catalog, type ModelInfo } from "../api";
import { money } from "../utils";

const HORIZON_LABEL: Record<string, string> = {
  daily: "daily brief",
  weekly: "weekly intelligence report",
  monthly: "monthly report",
};

export default function Configure() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiVersion, setApiVersion] = useState("2024-10-21");
  const [horizon, setHorizon] = useState("daily");
  const [deskCount, setDeskCount] = useState(5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Catalog>("/api/models").then((c) => {
      setCatalog(c);
      const activeProvider =
        c.current.provider && c.providers.some((p) => p.id === c.current.provider)
          ? c.current.provider
          : c.providers[0]?.id || "";
      setProvider(activeProvider);
      setDeskCount(c.desk_count || 5);
      const p = c.providers.find((x) => x.id === activeProvider);
      if (p) {
        setModel(
          c.current.model && p.models.some((m) => m.id === c.current.model) ? c.current.model : p.models[0]?.id || ""
        );
        setBaseUrl(c.current.provider === activeProvider && c.current.base_url ? c.current.base_url : p.base_url);
      }
      if (c.current.api_version) setApiVersion(c.current.api_version);
    });
  }, []);

  const currentProvider = useMemo(() => catalog?.providers.find((p) => p.id === provider) || null, [catalog, provider]);
  const currentModel: ModelInfo | null = useMemo(
    () => currentProvider?.models.find((m) => m.id === model) || null,
    [currentProvider, model]
  );
  const isAzure = currentProvider?.id === "azure_openai";

  function onProviderChange(id: string) {
    setProvider(id);
    const p = catalog?.providers.find((x) => x.id === id);
    if (p) {
      setModel(p.models[0]?.id || "");
      setBaseUrl(p.base_url);
    }
  }

  async function saveConfig(skipValidation: boolean) {
    setSaving(true);
    setError(null);
    try {
      const result = await api.post<{ provider: string; model: string }>("/api/configure", {
        api_key: apiKey.trim(),
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        api_version: isAzure ? apiVersion.trim() : undefined,
        skip_validation: skipValidation,
      });
      alert(`Configured successfully!\nProvider: ${result.provider}\nModel: ${result.model}`);
    } catch (e: any) {
      setError(e.message || "Configuration failed");
    } finally {
      setSaving(false);
    }
  }

  const cost = useMemo(() => {
    if (!catalog) return null;
    const measured = catalog.measured?.[horizon];
    const perDesk = measured
      ? { input: measured.input_per_desk, output: measured.output_per_desk }
      : catalog.tokens_per_desk_per_run[horizon];
    const runsPerMonth = catalog.runs_per_month[horizon];
    const inPrice = currentModel?.input || 0;
    const outPrice = currentModel?.output || 0;
    const runIn = perDesk.input * deskCount;
    const runOut = perDesk.output * deskCount;
    const runInCost = (runIn / 1e6) * inPrice;
    const runOutCost = (runOut / 1e6) * outPrice;
    const runCost = runInCost + runOutCost;
    const perDeskCost = runCost / deskCount;
    const monthly = runCost * runsPerMonth;
    const sourceNote = measured
      ? `Calibrated from ${measured.samples} actual run${measured.samples === 1 ? "" : "s"}`
      : "Modeled estimate — run a pipeline to calibrate from real usage";
    return { runIn, runOut, runInCost, runOutCost, runCost, perDeskCost, monthly, runsPerMonth, sourceNote, inPrice, outPrice };
  }, [catalog, currentModel, horizon, deskCount]);

  if (!catalog) return <div className="empty">Loading...</div>;

  return (
    <div>
      <h1>LLM Setup</h1>
      <p className="subtitle">
        Choose your model provider and estimate what each brief cadence will cost — one API key is all you need
        to run everything.
      </p>
      <div className="llm-setup-grid">
        <div className="panel">
          <h2>Provider &amp; Credentials</h2>
          {error && <p className="error-text" style={{ marginBottom: "var(--space-4)" }}>{error}</p>}
          <div className="form-group">
            <label>Provider</label>
            <select value={provider} onChange={(e) => onProviderChange(e.target.value)}>
              {catalog.providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>{isAzure ? "Deployment Name" : "Model"}</label>
            {currentProvider?.models.length ? (
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {currentProvider.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} — ${m.input}/${m.output} per 1M
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={isAzure ? "e.g. gpt-4o (your Azure deployment name)" : "(enter a custom model name)"}
              />
            )}
          </div>
          <div className="form-group">
            <label>API Key *</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={currentProvider?.key_hint || "your-api-key"}
            />
          </div>
          <div className="form-group">
            <label>{isAzure ? "Azure Endpoint *" : "Base URL"}</label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={isAzure ? "https://<your-resource>.openai.azure.com/" : "https://api.openai.com/v1"}
            />
            {isAzure && (
              <p style={{ marginTop: "var(--space-2)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
                Found on your Azure OpenAI resource's "Keys and Endpoint" page.
              </p>
            )}
            <p style={{ marginTop: "var(--space-2)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
              {currentProvider?.docs ? (
                <>
                  Get a key:{" "}
                  <a className="link" href={currentProvider.docs} target="_blank" rel="noreferrer">
                    {currentProvider.docs}
                  </a>
                </>
              ) : (
                "Enter the base URL for your OpenAI-compatible endpoint."
              )}
            </p>
          </div>
          {isAzure && (
            <div className="form-group">
              <label>API Version</label>
              <input
                type="text"
                value={apiVersion}
                onChange={(e) => setApiVersion(e.target.value)}
                placeholder="2024-10-21"
              />
              <p style={{ marginTop: "var(--space-2)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
                Azure OpenAI REST API version for your resource/deployment.
              </p>
            </div>
          )}
          <button className="btn btn-primary" disabled={saving} onClick={() => saveConfig(false)}>
            Save &amp; Validate
          </button>
          <p style={{ marginTop: "var(--space-4)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
            Supports OpenAI, Anthropic (Claude), Azure OpenAI, Google Gemini, xAI, Mistral, and any
            OpenAI-compatible endpoint.
          </p>
          <p style={{ marginTop: "var(--space-2)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
            On a corporate network? If validation fails due to connectivity, you can{" "}
            <button
              className="link"
              onClick={() => {
                if (confirm("Save API key without validating connectivity? Use this only if your network blocks the validation check.")) {
                  saveConfig(true);
                }
              }}
            >
              save without validation
            </button>{" "}
            and test when running the pipeline.
          </p>
        </div>

        <div className="panel cost-panel">
          <h2>Live Cost Projection</h2>
          <p style={{ fontSize: "var(--text-small)", color: "var(--color-muted)", marginBottom: "var(--space-6)" }}>
            Projected LLM spend for the selected model, based on your service desk horizon and number of tech desks.
          </p>
          <div className="form-row">
            <div className="form-group">
              <label>Service desk horizon</label>
              <select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                <option value="daily">Daily brief</option>
                <option value="weekly">Weekly intelligence</option>
                <option value="monthly">Monthly report</option>
              </select>
            </div>
            <div className="form-group">
              <label>Tech desks</label>
              <input
                type="number"
                min={1}
                max={100}
                value={deskCount}
                onChange={(e) => setDeskCount(Math.max(1, parseInt(e.target.value || "1", 10)))}
              />
            </div>
          </div>

          {cost && (
            <>
              <div className="cost-headline">
                <div>
                  <div className="card-label">One-time generation</div>
                  <div className="cost-amount">{money(cost.runCost)}</div>
                  <div className="cost-note">
                    One {HORIZON_LABEL[horizon]} across {deskCount} tech desk{deskCount === 1 ? "" : "s"} ·{" "}
                    {cost.sourceNote}
                  </div>
                </div>
                <div className="cost-secondary">
                  <div>
                    <span className="card-label">Per tech desk</span>
                    <div className="cost-sub">{money(cost.perDeskCost)}</div>
                  </div>
                  <div>
                    <span className="card-label">Total tokens</span>
                    <div className="cost-sub">{(cost.runIn + cost.runOut).toLocaleString()}</div>
                  </div>
                </div>
              </div>

              <div className="cost-breakdown">
                <div className="cost-row">
                  <span className="k">Model</span>
                  <span className="v">{currentModel?.label || model || "—"}</span>
                </div>
                <div className="cost-row">
                  <span className="k">Input price</span>
                  <span className="v">${cost.inPrice.toFixed(2)} / 1M tokens</span>
                </div>
                <div className="cost-row">
                  <span className="k">Output price</span>
                  <span className="v">${cost.outPrice.toFixed(2)} / 1M tokens</span>
                </div>
                <div className="cost-row">
                  <span className="k">Input tokens</span>
                  <span className="v">
                    {cost.runIn.toLocaleString()} → {money(cost.runInCost)}
                  </span>
                </div>
                <div className="cost-row">
                  <span className="k">Output tokens</span>
                  <span className="v">
                    {cost.runOut.toLocaleString()} → {money(cost.runOutCost)}
                  </span>
                </div>
                <div className="cost-row">
                  <span className="k">Tech desks</span>
                  <span className="v">{deskCount}</span>
                </div>
                {!currentModel && (
                  <div className="cost-row">
                    <span className="k">Note</span>
                    <span className="v">No list price for this model — set one via the API.</span>
                  </div>
                )}
              </div>

              <div className="cost-recurring">
                If you run this {HORIZON_LABEL[horizon]} on its normal cadence (~
                {cost.runsPerMonth % 1 === 0 ? cost.runsPerMonth : cost.runsPerMonth.toFixed(2)}
                ×/month), recurring spend is about <strong>{money(cost.monthly)}/month</strong> (~
                {money(cost.monthly * 12)}/year).
              </div>
            </>
          )}

          <p style={{ marginTop: "var(--space-4)", fontSize: "var(--text-small)", color: "var(--color-muted)" }}>
            Figures use public list prices and modeled token volumes for planning only. Confirm against your
            provider's current pricing.
          </p>
        </div>
      </div>
    </div>
  );
}
