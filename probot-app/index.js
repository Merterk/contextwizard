const axios = require("axios");

async function sendToBackend(context, payloadForBackend) {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    context.log.error("BACKEND_URL is not set in environment variables");
    return;
  }

  context.log.info("Sending payload to backend", payloadForBackend);

  try {
    const response = await axios.post(backendUrl, payloadForBackend);
    const backendData = response.data;

    const commentBody = backendData.comment;
    if (!commentBody || !commentBody.trim()) {
      context.log("Backend returned empty comment, skipping.");
      return;
    }

    const issueComment = context.issue({ body: commentBody });
    await context.octokit.issues.createComment(issueComment);
    context.log.info("Posted comment from backend on PR.");
  } catch (error) {
    context.log.error("Error calling backend or posting comment", error);
  }
}

module.exports = (app) => {
  // Helper to fetch all changed files for a PR
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
          status: f.status, // added / modified / removed
          additions: f.additions,
          deletions: f.deletions,
          changes: f.changes,
          patch: f.patch // diff hunk (can be long)
        });
      }

      if (res.data.length < 100) break;
      page += 1;
    }
    return files;
  }

  // 1) Full review submission (Approve / Request changes / Comment)
  app.on("pull_request_review.submitted", async (context) => {
    const review = context.payload.review;
    const pr = context.payload.pull_request;
    const repo = context.payload.repository;

    const reviewBody = review.body || "";
    if (!reviewBody.trim()) {
      context.log("Review body is empty, skipping.");
      return;
    }

    const ownerLogin = repo.owner && repo.owner.login;
    const repoName = repo.name;
    const prNumber = pr.number;

    const files = await getPrFiles(context, ownerLogin, repoName, prNumber);

    const payloadForBackend = {
      kind: "review",
      review_body: reviewBody,
      review_state: review.state,
      reviewer_login: review.user && review.user.login,
      pr_number: prNumber,
      pr_title: pr.title,
      pr_body: pr.body,
      pr_author_login: pr.user && pr.user.login,
      repo_full_name: repo.full_name,
      repo_owner: ownerLogin,
      repo_name: repoName,
      comment_body: null,
      comment_path: null,
      comment_diff_hunk: null,
      comment_position: null,
      files
    };

    await sendToBackend(context, payloadForBackend);
  });

  // 2) Single-line review comments (inline comments on Files changed)
  app.on("pull_request_review_comment.created", async (context) => {
    const comment = context.payload.comment;
    const pr = context.payload.pull_request;
    const repo = context.payload.repository;

    const commentBody = comment.body || "";
    if (!commentBody.trim()) {
      context.log("Inline comment body is empty, skipping.");
      return;
    }

    const ownerLogin = repo.owner && repo.owner.login;
    const repoName = repo.name;
    const prNumber = pr.number;

    const files = await getPrFiles(context, ownerLogin, repoName, prNumber);

    const payloadForBackend = {
      kind: "review_comment",
      review_body: null,
      review_state: null,
      reviewer_login: comment.user && comment.user.login,
      pr_number: prNumber,
      pr_title: pr.title,
      pr_body: pr.body,
      pr_author_login: pr.user && pr.user.login,
      repo_full_name: repo.full_name,
      repo_owner: ownerLogin,
      repo_name: repoName,
      // specific info about this inline comment:
      comment_body: commentBody,
      comment_path: comment.path, // file path
      comment_diff_hunk: comment.diff_hunk, // snippet around the comment
      comment_position: comment.position,   // position in diff (may be null in some modes)
      files
    };

    await sendToBackend(context, payloadForBackend);
  });
};
