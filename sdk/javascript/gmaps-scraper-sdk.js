/**
 * Google Maps Lead Scraper — JavaScript / Node.js SDK
 * =====================================================
 * Works in Node.js 18+ (native fetch) and browser.
 * No dependencies — uses built-in fetch + EventSource.
 *
 * Install (Node.js): just copy this file, no npm needed.
 *
 * USAGE EXAMPLES:
 *
 * const client = new LeadScraperClient("http://localhost:8000");
 *
 * // 1. Simple sync scrape
 * const leads = await client.scrape("Dentists in Mathura", { maxResults: 50 });
 *
 * // 2. Async job with polling
 * const job = await client.createJob("Gyms in Delhi", { maxResults: 200 });
 * const results = await client.waitForJob(job.job_id);
 *
 * // 3. Live stream — get leads as they're scraped
 * await client.streamJob("Restaurants in Agra", { maxResults: 100 }, (lead) => {
 *   console.log("Found:", lead.name, lead.phone);
 * });
 */

class LeadScraperError extends Error {
  constructor(message, statusCode = null) {
    super(message);
    this.name = "LeadScraperError";
    this.statusCode = statusCode;
  }
}

class LeadScraperClient {
  /**
   * @param {string} baseUrl  - Your API URL e.g. "http://localhost:8000"
   * @param {object} options
   * @param {number} options.timeout    - Fetch timeout ms (default 600000 = 10min)
   * @param {string} options.apiKey     - Optional API key
   */
  constructor(baseUrl = "http://localhost:8000", options = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.timeout = options.timeout ?? 600_000;
    this.apiKey = options.apiKey ?? null;
  }

  // ── Core API ───────────────────────────────────────────────────────────────

  /**
   * Synchronous scrape — waits for all results.
   * @param {string} query        - e.g. "Dentists in Mathura"
   * @param {object} opts
   * @param {number} opts.maxResults     - Max leads (default 50, max 1000)
   * @param {boolean} opts.extractDetails - Full details per place (default true)
   * @returns {Promise<Array>} Array of lead objects
   *
   * @example
   * const leads = await client.scrape("Dentists in Mathura", { maxResults: 50 });
   * leads.forEach(l => console.log(l.name, l.phone, l.rating));
   */
  async scrape(query, opts = {}) {
    const data = await this._post("/scrape", {
      query,
      max_results: opts.maxResults ?? 50,
      extract_details: opts.extractDetails ?? true,
    });
    return data.data ?? [];
  }

  /**
   * Submit an async job — returns immediately with job info.
   * @param {string} query
   * @param {object} opts
   * @param {number}  opts.maxResults
   * @param {boolean} opts.extractDetails
   * @param {string}  opts.webhookUrl - Optional webhook to POST results to when done
   * @returns {Promise<object>} { job_id, status, query, created_at }
   *
   * @example
   * const job = await client.createJob("Gyms in Delhi", { maxResults: 200 });
   * console.log("Job ID:", job.job_id);
   */
  async createJob(query, opts = {}) {
    return this._post("/jobs", {
      query,
      max_results: opts.maxResults ?? 100,
      extract_details: opts.extractDetails ?? true,
      webhook_url: opts.webhookUrl ?? null,
    });
  }

  /**
   * Poll a job's current status.
   * @returns {Promise<object>} { job_id, status, progress, results_so_far, ... }
   */
  async pollJob(jobId) {
    return this._get(`/jobs/${jobId}`);
  }

  /**
   * Get full results for a completed job.
   * @returns {Promise<Array>} Array of leads
   */
  async getResults(jobId) {
    const data = await this._get(`/jobs/${jobId}/results`);
    return data.data ?? [];
  }

  /**
   * Submit job and poll until complete. Logs progress to console.
   * @param {string} jobId
   * @param {object} opts
   * @param {number}  opts.pollInterval - ms between polls (default 3000)
   * @param {boolean} opts.verbose      - log progress (default true)
   * @returns {Promise<Array>} Final leads array
   *
   * @example
   * const job = await client.createJob("Gyms in Delhi", { maxResults: 200 });
   * const leads = await client.waitForJob(job.job_id);
   */
  async waitForJob(jobId, opts = {}) {
    const interval = opts.pollInterval ?? 3000;
    const verbose = opts.verbose ?? true;

    while (true) {
      const status = await this.pollJob(jobId);
      const { status: st, progress, results_so_far, execution_time } = status;

      if (verbose) {
        process.stdout && process.stdout.write
          ? process.stdout.write(`\r  [${st.toUpperCase()}] ${progress}% — ${results_so_far} leads...`)
          : console.log(`[${st}] ${progress}% — ${results_so_far} leads`);
      }

      if (st === "completed") {
        if (verbose) console.log(`\n  ✅ Done! ${results_so_far} leads in ${execution_time}`);
        return this.getResults(jobId);
      }

      if (st === "failed") {
        throw new LeadScraperError(`Job failed: ${status.error}`);
      }

      await new Promise(r => setTimeout(r, interval));
    }
  }

  /**
   * Submit a job and stream results live via SSE.
   * Callback fires for EVERY lead as it's found.
   *
   * @param {string}   query
   * @param {object}   opts         - same as createJob opts
   * @param {function} onLead       - called with each lead dict
   * @param {function} onDone       - called when complete with { total }
   * @returns {Promise<void>}
   *
   * @example
   * await client.streamJob("Restaurants in Agra", { maxResults: 100 },
   *   (lead) => console.log("Got:", lead.name, lead.phone),
   *   (summary) => console.log("Total:", summary.total)
   * );
   */
  async streamJob(query, opts = {}, onLead = null, onDone = null) {
    const job = await this.createJob(query, opts);
    const jobId = job.job_id;

    return new Promise((resolve, reject) => {
      const url = `${this.baseUrl}/jobs/${jobId}/stream`;

      // Use EventSource if available (browser), else fetch stream (Node)
      if (typeof EventSource !== "undefined") {
        const es = new EventSource(url);
        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (event.type === "result" && onLead) onLead(event.lead);
            if (event.type === "done") {
              es.close();
              if (onDone) onDone({ total: event.total, status: event.status });
              resolve();
            }
            if (event.type === "error") {
              es.close();
              reject(new LeadScraperError(event.error));
            }
          } catch (err) { /* skip malformed */ }
        };
        es.onerror = (e) => { es.close(); reject(new LeadScraperError("SSE connection error")); };
      } else {
        // Node.js fetch streaming
        fetch(url, { signal: AbortSignal.timeout(this.timeout) })
          .then(async (res) => {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop();
              for (const line of lines) {
                if (!line.startsWith("data:")) continue;
                try {
                  const event = JSON.parse(line.slice(5).trim());
                  if (event.type === "result" && onLead) onLead(event.lead);
                  if (event.type === "done") {
                    if (onDone) onDone({ total: event.total, status: event.status });
                    resolve(); return;
                  }
                  if (event.type === "error") {
                    reject(new LeadScraperError(event.error)); return;
                  }
                } catch { /* skip */ }
              }
            }
            resolve();
          })
          .catch(reject);
      }
    });
  }

  /**
   * List all jobs on the server.
   * @returns {Promise<Array>}
   */
  async listJobs() {
    return this._get("/jobs");
  }

  /**
   * Delete a job.
   */
  async deleteJob(jobId) {
    const res = await fetch(`${this.baseUrl}/jobs/${jobId}`, {
      method: "DELETE",
      headers: this._headers(),
    });
    if (!res.ok) throw new LeadScraperError(`Delete failed: ${res.status}`);
    return res.json();
  }

  /**
   * Get download URL for CSV export.
   * In Node.js, this downloads and saves the file.
   * In browser, triggers a file download.
   */
  async downloadCsv(jobId, filename = null) {
    const url = `${this.baseUrl}/jobs/${jobId}/export?format=csv`;
    return this._download(url, filename ?? `leads_${jobId.slice(0,8)}.csv`);
  }

  /**
   * Get download URL for Excel export.
   */
  async downloadExcel(jobId, filename = null) {
    const url = `${this.baseUrl}/jobs/${jobId}/export?format=xlsx`;
    return this._download(url, filename ?? `leads_${jobId.slice(0,8)}.xlsx`);
  }

  /**
   * Check API health.
   */
  async health() {
    return this._get("/health");
  }

  /**
   * Get scraping metrics.
   */
  async metrics() {
    return this._get("/metrics");
  }

  // ── Utility ────────────────────────────────────────────────────────────────

  /** Convert leads array to CSV string */
  leadsToCSV(leads) {
    if (!leads.length) return "";
    const fields = Object.keys(leads[0]);
    const escape = (v) => {
      if (v === null || v === undefined) return "";
      const s = Array.isArray(v) ? v.join(" | ") : String(v);
      return s.includes(",") || s.includes('"') || s.includes("\n")
        ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return [
      fields.join(","),
      ...leads.map(l => fields.map(f => escape(l[f])).join(","))
    ].join("\n");
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  _headers() {
    const h = { "Content-Type": "application/json", "Accept": "application/json" };
    if (this.apiKey) h["X-API-Key"] = this.apiKey;
    return h;
  }

  async _post(path, body) {
    let res;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: this._headers(),
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(this.timeout),
      });
    } catch (e) {
      throw new LeadScraperError(`Network error: ${e.message}`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new LeadScraperError(err.detail ?? `HTTP ${res.status}`, res.status);
    }
    return res.json();
  }

  async _get(path) {
    let res;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        headers: this._headers(),
        signal: AbortSignal.timeout(this.timeout),
      });
    } catch (e) {
      throw new LeadScraperError(`Network error: ${e.message}`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new LeadScraperError(err.detail ?? `HTTP ${res.status}`, res.status);
    }
    return res.json();
  }

  async _download(url, filename) {
    // Browser
    if (typeof window !== "undefined") {
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      return url;
    }
    // Node.js
    const { writeFileSync } = await import("fs");
    const res = await fetch(url, { headers: this._headers() });
    if (!res.ok) throw new LeadScraperError(`Download failed: ${res.status}`);
    const buf = await res.arrayBuffer();
    writeFileSync(filename, Buffer.from(buf));
    console.log(`✅ Saved to ${filename}`);
    return filename;
  }
}

// ── Quick Node.js CLI demo ─────────────────────────────────────────────────────

if (typeof process !== "undefined" && process.argv?.[1]?.endsWith("gmaps-scraper-sdk.js")) {
  const baseUrl = process.argv[2] ?? "http://localhost:8000";
  const query   = process.argv[3] ?? "Dentists in Mathura";
  const count   = parseInt(process.argv[4] ?? "20");

  (async () => {
    console.log(`\n🔍 Scraping: "${query}" (max ${count})`);
    console.log(`🌐 API: ${baseUrl}\n`);

    const client = new LeadScraperClient(baseUrl);

    const h = await client.health();
    console.log(`✅ API healthy | Browsers: ${h.browser_pool.active}/${h.browser_pool.pool_size}\n`);

    console.log("🚀 Streaming results live...\n");
    const all = [];
    await client.streamJob(query, { maxResults: count },
      (lead) => {
        all.push(lead);
        console.log(`  [${all.length}] ${lead.name} | ⭐${lead.rating ?? "?"} | 📞${lead.phone ?? "N/A"}`);
      },
      (summary) => console.log(`\n🏁 Done! Total: ${summary.total}`)
    );

    const csv = client.leadsToCSV(all);
    const { writeFileSync } = await import("fs");
    const fname = `leads_${query.slice(0,15).replace(/ /g,"_")}.csv`;
    writeFileSync(fname, csv);
    console.log(`\n💾 Saved: ${fname}`);
  })().catch(console.error);
}

// Export for Node.js
if (typeof module !== "undefined") module.exports = { LeadScraperClient, LeadScraperError };
