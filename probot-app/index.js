// probot-app/index.js
const axios = require("axios");

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

  const files = await getPrFiles(context, owner, repoName, prNumber);

  return {
    kind: "review_comment",

    // review-level fields (unused for this kind)
    review_body: null,
    review_state: null,

    // inline comment fields
    comment_body: commentBodyOriginal,
    comment_path: comment.path,
    comment_diff_hunk: comment.diff_hunk,
    comment_position: comment.position,
    comment_id: comment.id,

    // shared metadata
    reviewer_login: comment.user && comment.user.login,
    pr_number: prNumber,
    pr_title: pr.title,
    pr_body: pr.body,
    pr_author_login: pr.user && pr.user.login,
    repo_full_name: repo.full_name,
    repo_owner: owner,
    repo_name: repoName,

    // diff context
    files,

    // not included for single inline comment
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
 * Main Probot app
 */
module.exports = (app) => {
  // We intentionally IGNORE pull_request_review.submitted for now to avoid double-processing.
  // (When you re-enable later, add a separate handler with its own logic.)

  // Handle single inline review comment on “Files changed”
  app.on("pull_request_review_comment.created", async (context) => {
    try {
      if (isFromBot(context)) {
        context.log.info("Skipping event from bot sender.");
        return;
      }

      const payloadForBackend = await buildReviewCommentPayload(context);
      if (!payloadForBackend) {
        context.log.info("Inline comment body empty, skipping.");
        return;
      }

      const replyBody = await callBackend(context, payloadForBackend);
      if (!replyBody) return;

      const repo = context.payload.repository;
      const pr = context.payload.pull_request;
      const comment = context.payload.comment;

      const owner = repo.owner.login;
      const repoName = repo.name;
      const prNumber = pr.number;

      await replyToInlineComment(context, owner, repoName, prNumber, comment.id, replyBody);

      context.log.info(
        { pr: prNumber, comment_id: comment.id },
        "Replied to inline review comment."
      );
    } catch (err) {
      context.log.error({ err }, "Error while handling pull_request_review_comment.created");
    }
  });
};
