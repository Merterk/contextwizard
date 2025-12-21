// probot-app/index.js
const axios = require("axios");

/**
 * Config path for optional repo-based context docs (FR2.3)
 */
const CONTEXTWIZARD_CONFIG_PATH =
  process.env.CONTEXTWIZARD_CONFIG_PATH || ".contextwizard.json";

/**
 * Env
 */
function getBackendUrl(context) {
  const url = process.env.BACKEND_URL;
  if (!url) {
    context.log.error("BACKEND_URL is not set in environment variables");
    return null;
  }
  return url;
}

/**
 * Ignore events from bots (your app, dependabot, etc.)
 */
function isFromBot(context) {
  const sender = context.payload.sender;
  if (!sender) return false;
  if (sender.type === "Bot") return true;
  if (sender.login && sender.login.endsWith("[bot]")) return true;
  return false;
}

/**
 * Call backend: POST payload -> expects { comment: string }
 */
async function callBackend(context, payloadForBackend) {
  const backendUrl = getBackendUrl(context);
  if (!backendUrl) return null;

  context.log.info(
    { kind: payloadForBackend.kind, pr: payloadForBackend.pr_number },
    "Sending payload to backend"
  );

  try {
    const res = await axios.post(backendUrl, payloadForBackend, {
      headers: { "Content-Type": "application/json" },
      timeout: 30_000
    });

    const commentBody = res?.data?.comment;
    if (!commentBody || !commentBody.trim()) {
      context.log.info("Backend returned empty comment, skipping.");
      return null;
    }
    return commentBody;
  } catch (err) {
    context.log.error({ err }, "Error calling backend");
    return null;
  }
}

/**
 * Helper: fetch changed files for a PR (includes unified diff patch when available)
 */
async function getPrFiles(context, owner, repo, prNumber) {
  const files = [];
  let page = 1;

  while (true) {
    const res = await context.octokit.pulls.listFiles({
      owner,
      repo,
      pull_number: prNumber,
      per_page: 100,
      page
    });

    if (!res.data.length) break;

    for (const f of res.data) {
      files.push({
        filename: f.filename,
        status: f.status,
        additions: f.additions,
        deletions: f.deletions,
        changes: f.changes,
        patch: f.patch
      });
    }

    if (res.data.length < 100) break;
    page += 1;
  }

  return files;
}

async function getPullRequest(context, owner, repo, prNumber) {
  const res = await context.octokit.pulls.get({
    owner,
    repo,
    pull_number: prNumber
  });
  return res.data;
}

/**
 * -----------------------------
 * Optional project context (FR2.3)
 * Supports explicit docs[] OR scanning a directory for extensions
 * -----------------------------
 */
const _ctxCache = new Map(); // `${owner}/${repo}` -> { at, docs }
const CACHE_TTL_MS = Number(process.env.CONTEXTWIZARD_CACHE_TTL_MS || "300000"); // 5 min
const DEFAULT_MAX_DOCS = Number(process.env.CONTEXTWIZARD_MAX_DOCS || "4");
const DEFAULT_MAX_CHARS = Number(process.env.CONTEXTWIZARD_MAX_DOC_CHARS || "6000");
const DEFAULT_MAX_TOTAL_CHARS = Number(process.env.CONTEXTWIZARD_MAX_TOTAL_CHARS || "20000");

async function fetchRepoFileText(context, owner, repo, path, ref) {
  try {
    const res = await context.octokit.repos.getContent({
      owner,
      repo,
      path,
      ref,
      mediaType: { format: "raw" }
    });

    if (typeof res.data === "string") return res.data;
    if (Buffer.isBuffer(res.data)) return res.data.toString("utf8");

    if (res.data && res.data.content) {
      const buff = Buffer.from(res.data.content, res.data.encoding || "base64");
      return buff.toString("utf8");
    }
  } catch (e) {
    // ignore missing files, permission issues, etc.
  }
  return null;
}

async function loadContextWizardConfig(context, owner, repo, ref) {
  // Env override: comma-separated paths (explicit mode)
  const envDocs = (process.env.CONTEXTWIZARD_DOCS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  if (envDocs.length) {
    return {
      docs: envDocs.map((p) => ({ path: p, kind: null })),
      scan: null,
      max_docs: DEFAULT_MAX_DOCS,
      max_chars_per_doc: DEFAULT_MAX_CHARS,
      max_total_chars: DEFAULT_MAX_TOTAL_CHARS
    };
  }

  const raw = await fetchRepoFileText(
    context,
    owner,
    repo,
    CONTEXTWIZARD_CONFIG_PATH,
    ref
  );
  if (!raw) return null;

  try {
    const cfg = JSON.parse(raw);
    const docs = Array.isArray(cfg.docs) ? cfg.docs : [];
    const scan = cfg.scan || null;

    return {
      docs: docs
        .map((d) => (typeof d === "string" ? { path: d, kind: null } : d))
        .filter(Boolean),
      scan,
      max_docs: Number(cfg.max_docs || DEFAULT_MAX_DOCS),
      max_chars_per_doc: Number(cfg.max_chars_per_doc || DEFAULT_MAX_CHARS),
      max_total_chars: Number(cfg.max_total_chars || DEFAULT_MAX_TOTAL_CHARS)
    };
  } catch (e) {
    context.log.warn({ e }, "Failed to parse .contextwizard.json");
    return null;
  }
}

// List repo files recursively using Git Trees API
async function listRepoFilesRecursive(context, owner, repo, branch) {
  // 1) Get SHA of branch head
  const refRes = await context.octokit.git.getRef({
    owner,
    repo,
    ref: `heads/${branch}`
  });
  const commitSha = refRes.data.object.sha;

  // 2) Get commit to find tree SHA
  const commitRes = await context.octokit.git.getCommit({
    owner,
    repo,
    commit_sha: commitSha
  });
  const treeSha = commitRes.data.tree.sha;

  // 3) Get full tree recursively
  const treeRes = await context.octokit.git.getTree({
    owner,
    repo,
    tree_sha: treeSha,
    recursive: "1"
  });

  const items = treeRes.data.tree || [];
  return items
    .filter((it) => it.type === "blob" && typeof it.path === "string")
    .map((it) => it.path);
}

function normalizeExt(ext) {
  if (!ext) return "";
  return ext.startsWith(".") ? ext.toLowerCase() : `.${ext.toLowerCase()}`;
}

async function getProjectContextDocs(context, owner, repo, defaultBranch) {
  const key = `${owner}/${repo}`;
  const now = Date.now();
  const cached = _ctxCache.get(key);
  if (cached && now - cached.at < CACHE_TTL_MS) return cached.docs;

  const cfg = await loadContextWizardConfig(context, owner, repo, defaultBranch);
  if (!cfg) {
    _ctxCache.set(key, { at: now, docs: [] });
    return [];
  }

  const maxDocs = Math.min(cfg.max_docs || DEFAULT_MAX_DOCS, 200); // hard safety
  const maxCharsPerDoc = Math.min(cfg.max_chars_per_doc || DEFAULT_MAX_CHARS, 20000);
  const maxTotalChars = Math.min(cfg.max_total_chars || DEFAULT_MAX_TOTAL_CHARS, 100000);

  let paths = [];

  // ---- Mode A: scan mode (your .rst folder scan)
  if (cfg.scan && cfg.scan.root && Array.isArray(cfg.scan.extensions)) {
    const root = String(cfg.scan.root).replace(/^\/+/, "").replace(/\/+$/, "");
    const exts = cfg.scan.extensions.map(normalizeExt).filter(Boolean);
    const kind = cfg.scan.kind || null;

    try {
      const allPaths = await listRepoFilesRecursive(context, owner, repo, defaultBranch);
      paths = allPaths.filter((p) => {
        const inRoot = p === root || p.startsWith(`${root}/`);
        if (!inRoot) return false;
        return exts.some((e) => p.toLowerCase().endsWith(e));
      });

      paths.sort((a, b) => a.localeCompare(b));

      const docsFromScan = paths.slice(0, maxDocs).map((p) => ({ path: p, kind }));
      cfg.docs = docsFromScan; // reuse explicit loading pipeline below
    } catch (e) {
      context.log.warn({ e }, "Scan mode failed; no project docs loaded.");
      _ctxCache.set(key, { at: now, docs: [] });
      return [];
    }
  }

  // ---- Mode B: explicit docs[] mode
  const docsList = Array.isArray(cfg.docs) ? cfg.docs : [];
  if (!docsList.length) {
    _ctxCache.set(key, { at: now, docs: [] });
    return [];
  }

  const out = [];
  let totalChars = 0;

  for (const d of docsList.slice(0, maxDocs)) {
    if (!d || !d.path) continue;
    if (totalChars >= maxTotalChars) break;

    const text = await fetchRepoFileText(context, owner, repo, d.path, defaultBranch);
    if (!text) continue;

    let excerpt =
      text.length > maxCharsPerDoc ? text.slice(0, maxCharsPerDoc) + "\n…(truncated)…" : text;

    const remaining = maxTotalChars - totalChars;
    if (excerpt.length > remaining) {
      excerpt = excerpt.slice(0, remaining) + "\n…(truncated to total cap)…";
    }

    out.push({
      path: d.path,
      kind: d.kind || null,
      url: `https://github.com/${owner}/${repo}/blob/${defaultBranch}/${d.path}`,
      excerpt
    });

    totalChars += excerpt.length;
    if (totalChars >= maxTotalChars) break;
  }

  _ctxCache.set(key, { at: now, docs: out });
  return out;
}

/**
 * Build backend payload for a single inline review comment event
 */
async function buildReviewCommentPayload(context) {
  const comment = context.payload.comment;
  const pr = context.payload.pull_request;
  const repo = context.payload.repository;

  const commentBodyOriginal = (comment.body || "").trim();
  if (!commentBodyOriginal) return null;

  const owner = repo.owner.login;
  const repoName = repo.name;
  const prNumber = pr.number;
  const defaultBranch = repo.default_branch;

  const files = await getPrFiles(context, owner, repoName, prNumber);
  const project_context_docs = await getProjectContextDocs(
    context,
    owner,
    repoName,
    defaultBranch
  );

  return {
    kind: "review_comment",

    review_body: null,
    review_state: null,

    comment_body: commentBodyOriginal,
    comment_path: comment.path,
    comment_diff_hunk: comment.diff_hunk,
    comment_position: comment.position,
    comment_id: comment.id,

    reviewer_login: comment.user && comment.user.login,
    pr_number: prNumber,
    pr_title: pr.title,
    pr_body: pr.body,
    pr_author_login: pr.user && pr.user.login,
    repo_full_name: repo.full_name,
    repo_owner: owner,
    repo_name: repoName,
    repo_default_branch: defaultBranch,

    files,
    project_context_docs,
    review_comments: null
  };
}

/**
 * Build backend payload for a submitted review event (top-level comment)
 */
async function buildReviewPayload(context) {
  const review = context.payload.review;
  const pr = context.payload.pull_request;
  const repo = context.payload.repository;

  const reviewBodyOriginal = (review.body || "").trim();
  if (!reviewBodyOriginal) return null;

  const owner = repo.owner.login;
  const repoName = repo.name;
  const prNumber = pr.number;
  const defaultBranch = repo.default_branch;

  const files = await getPrFiles(context, owner, repoName, prNumber);
  const project_context_docs = await getProjectContextDocs(
    context,
    owner,
    repoName,
    defaultBranch
  );

  return {
    kind: "review",

    review_body: reviewBodyOriginal,
    review_state: review.state,

    comment_body: null,
    comment_path: null,
    comment_diff_hunk: null,
    comment_position: null,
    comment_id: null,

    reviewer_login: review.user && review.user.login,
    pr_number: prNumber,
    pr_title: pr.title,
    pr_body: pr.body,
    pr_author_login: pr.user && pr.user.login,
    repo_full_name: repo.full_name,
    repo_owner: owner,
    repo_name: repoName,
    repo_default_branch: defaultBranch,

    files,
    project_context_docs,
    review_comments: null
  };
}

/**
 * Build backend payload for a normal PR conversation comment (issue_comment)
 */
async function buildIssueCommentPayload(context) {
  const repo = context.payload.repository;
  const issue = context.payload.issue;
  const comment = context.payload.comment;

  const owner = repo.owner.login;
  const repoName = repo.name;
  const prNumber = issue.number;
  const defaultBranch = repo.default_branch;

  const commentBody = (comment.body || "").trim();
  if (!commentBody) return null;

  const pr = await getPullRequest(context, owner, repoName, prNumber);
  const files = await getPrFiles(context, owner, repoName, prNumber);
  const project_context_docs = await getProjectContextDocs(
    context,
    owner,
    repoName,
    defaultBranch
  );

  return {
    kind: "issue_comment",

    review_body: null,
    review_state: null,

    comment_body: commentBody,
    comment_path: null,
    comment_diff_hunk: null,
    comment_position: null,
    comment_id: comment.id,

    reviewer_login: comment.user && comment.user.login,
    pr_number: prNumber,
    pr_title: pr.title,
    pr_body: pr.body,
    pr_author_login: pr.user && pr.user.login,
    repo_full_name: repo.full_name,
    repo_owner: owner,
    repo_name: repoName,
    repo_default_branch: defaultBranch,

    files,
    project_context_docs,
    review_comments: null
  };
}

/**
 * Post reply to the inline comment thread
 */
async function replyToInlineComment(context, owner, repoName, prNumber, commentId, body) {
  await context.octokit.pulls.createReplyForReviewComment({
    owner,
    repo: repoName,
    pull_number: prNumber,
    comment_id: commentId,
    body
  });
}

/**
 * Post reply to the top-level PR thread (issues comment API)
 */
async function replyToPrThread(context, owner, repoName, prNumber, body) {
  await context.octokit.issues.createComment({
    owner,
    repo: repoName,
    issue_number: prNumber,
    body
  });
}

/**
 * Main Probot app
 */
module.exports = (app) => {
  // ----------------------------------------------
  // 1) Handle single inline review comment
  // ----------------------------------------------
  app.on("pull_request_review_comment.created", async (context) => {
    try {
      if (isFromBot(context)) return;

      const commentBody = (context.payload.comment.body || "").trim();
      const isWizardCmd = commentBody.startsWith("/wizard-review");

      const payloadForBackend = await buildReviewCommentPayload(context);
      if (!payloadForBackend) return;

      if (isWizardCmd) {
        payloadForBackend.kind = "wizard_review_command";
      }

      const replyBody = await callBackend(context, payloadForBackend);
      if (!replyBody) return;

      const owner = payloadForBackend.repo_owner;
      const repoName = payloadForBackend.repo_name;
      const prNumber = payloadForBackend.pr_number;

      await replyToInlineComment(
        context,
        owner,
        repoName,
        prNumber,
        context.payload.comment.id,
        replyBody
      );
    } catch (err) {
      context.log.error({ err }, "Error in pull_request_review_comment.created handler");
    }
  });

  // ----------------------------------------------
  // 2) Handle submitted Pull Request Review (top-level comment)
  // ----------------------------------------------
  app.on("pull_request_review.submitted", async (context) => {
    try {
      if (isFromBot(context)) return;

      const reviewBody = context.payload.review.body;
      if (!reviewBody || reviewBody.trim() === "") return;

      const payloadForBackend = await buildReviewPayload(context);
      if (!payloadForBackend) return;

      const replyBody = await callBackend(context, payloadForBackend);
      if (!replyBody) return;

      const repo = context.payload.repository;
      const pr = context.payload.pull_request;

      const owner = repo.owner.login;
      const repoName = repo.name;
      const prNumber = pr.number;

      await replyToPrThread(context, owner, repoName, prNumber, replyBody);
    } catch (err) {
      context.log.error({ err }, "Error while handling pull_request_review.submitted");
    }
  });

  // ----------------------------------------------
  // 3) Handle normal PR conversation comments (issue_comment) - NO REVIEW
  // ----------------------------------------------
  app.on("issue_comment.created", async (context) => {
    try {
      if (isFromBot(context)) return;

      const issue = context.payload.issue;
      if (!issue || !issue.pull_request) return;

      const body = (context.payload.comment.body || "").trim();
      if (!body) return;

      const isWizardCmd = body.startsWith("/wizard-review");

      const payloadForBackend = await buildIssueCommentPayload(context);
      if (!payloadForBackend) return;

      if (isWizardCmd) payloadForBackend.kind = "wizard_review_command";

      const replyBody = await callBackend(context, payloadForBackend);
      if (!replyBody) return;

      const repo = context.payload.repository;
      const owner = repo.owner.login;
      const repoName = repo.name;
      const prNumber = issue.number;

      const commenter = context.payload.comment.user && context.payload.comment.user.login;
      const finalBody =
        !isWizardCmd && commenter ? `@${commenter} ${replyBody}` : replyBody;

      await replyToPrThread(context, owner, repoName, prNumber, finalBody);
    } catch (err) {
      context.log.error({ err }, "Error while handling issue_comment.created for PR");
    }
  });
};
