// probot-app/index.js
const axios = require("axios");

module.exports = (app) => {
  app.on("pull_request_review.submitted", async (context) => {
    const review = context.payload.review;
    const pullRequest = context.payload.pull_request;
    const repository = context.payload.repository;

    const reviewBody = review.body || "";
    if (!reviewBody.trim()) {
      context.log("Review body is empty, skipping.");
      return;
    }

    const backendUrl = process.env.BACKEND_URL;
    if (!backendUrl) {
      context.log.error("BACKEND_URL is not set in environment variables");
      return;
    }

    const payloadForBackend = {
      review_body: reviewBody,
      review_state: review.state,
      reviewer_login: review.user && review.user.login,
      pr_number: pullRequest.number,
      pr_title: pullRequest.title,
      pr_body: pullRequest.body,
      pr_author_login: pullRequest.user && pullRequest.user.login,
      repo_full_name: repository.full_name,
      repo_owner: repository.owner && repository.owner.login,
      repo_name: repository.name
    };

    context.log.info("Sending payload to backend", payloadForBackend);

    try {
      const response = await axios.post(backendUrl, payloadForBackend);
      const backendData = response.data;

      const commentBody = backendData.comment;
      if (!commentBody || !commentBody.trim()) {
        context.log("Backend returned empty comment, skipping.");
        return;
      }

      const issueComment = context.issue({
        body: commentBody
      });

      await context.octokit.issues.createComment(issueComment);
      context.log.info("Posted comment from backend on PR.");
    } catch (error) {
      context.log.error("Error calling backend or posting comment", error);
    }
  });
};
