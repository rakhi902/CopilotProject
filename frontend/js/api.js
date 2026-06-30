/*
 * Job Application Co-Pilot - API client.
 *
 * Thin fetch() wrappers around the FastAPI backend, exposed as a single global
 * `window.API`. There is no build step and no module system on purpose: this is
 * a plain script tag, so everything is wrapped in an IIFE to avoid leaking names
 * other than `window.API`.
 */
(function () {
  "use strict";

  // Where the FastAPI backend lives. Change this if you host the API elsewhere.
  var API_BASE = "http://127.0.0.1:8000";

  // localStorage key under which the JWT access token is persisted between visits.
  var TOKEN_KEY = "jobcopilot_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }
  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }
  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  /**
   * A small custom error so the UI can branch on `.status` (e.g. 401 -> log out)
   * and show the server's `.detail` message.
   * @param {string} message  Human-readable message.
   * @param {number} status   HTTP status (0 means the network request failed).
   * @param {*} detail        The parsed `detail` field from the API, if any.
   */
  function ApiError(message, status, detail) {
    this.name = "ApiError";
    this.message = message;
    this.status = status;
    this.detail = detail;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function parseJsonSafely(text) {
    try {
      return JSON.parse(text);
    } catch (parseError) {
      return null;
    }
  }

  /**
   * The single low-level request helper every endpoint below is built on.
   *
   * @param {string} path  API path beginning with "/", e.g. "/auth/login".
   * @param {object} [options]  { method, body, form, auth }.
   *   - body: a plain object sent as JSON.
   *   - form: a FormData instance sent as multipart (mutually exclusive with body).
   *   - auth: when true, attach the bearer token.
   * @returns {Promise<*>}  Parsed JSON, or null for an empty body.
   * @throws {ApiError}  On network failure or any non-2xx response.
   */
  async function request(path, options) {
    options = options || {};
    var headers = {};

    var token = getToken();
    if (options.auth && token) {
      headers["Authorization"] = "Bearer " + token;
    }

    var fetchOptions = { method: options.method || "GET", headers: headers };

    if (options.form) {
      // Let the browser set the multipart Content-Type (with its boundary).
      fetchOptions.body = options.form;
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      fetchOptions.body = JSON.stringify(options.body);
    }

    var response;
    try {
      response = await fetch(API_BASE + path, fetchOptions);
    } catch (networkError) {
      // fetch only rejects on network-level failures (server down, CORS, offline).
      throw new ApiError("Could not reach the server. Is the backend running?", 0, null);
    }

    var rawText = await response.text();
    var data = rawText ? parseJsonSafely(rawText) : null;

    if (!response.ok) {
      var detail = data && data.detail !== undefined ? data.detail : response.statusText;
      var message = typeof detail === "string" ? detail : "Request failed (" + response.status + ").";
      throw new ApiError(message, response.status, detail);
    }
    return data;
  }

  /**
   * Like ``request`` but for binary file downloads: returns a Blob on success.
   * @param {string} path  API path (e.g. "/roles/1/export/resume.pdf").
   * @returns {Promise<Blob>}
   * @throws {ApiError}
   */
  async function requestBlob(path) {
    var headers = {};
    var token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;

    var response;
    try {
      response = await fetch(API_BASE + path, { headers: headers });
    } catch (networkError) {
      throw new ApiError("Could not reach the server. Is the backend running?", 0, null);
    }
    if (!response.ok) {
      var rawText = await response.text();
      var data = rawText ? parseJsonSafely(rawText) : null;
      var detail = data && data.detail !== undefined ? data.detail : response.statusText;
      var message = typeof detail === "string" ? detail : "Download failed (" + response.status + ").";
      throw new ApiError(message, response.status, detail);
    }
    return await response.blob();
  }

  // The public surface. Each method maps to exactly one backend endpoint.
  var API = {
    base: API_BASE,
    ApiError: ApiError,
    isAuthenticated: function () { return !!getToken(); },
    getToken: getToken,
    clearToken: clearToken,

    /** Register a new account. payload: { email, full_name?, password }. */
    register: function (payload) {
      return request("/auth/register", { method: "POST", body: payload });
    },

    /** Log in; on success the access token is stored for subsequent calls. */
    login: async function (payload) {
      var data = await request("/auth/login", { method: "POST", body: payload });
      if (data && data.access_token) {
        setToken(data.access_token);
      }
      return data;
    },

    /** Fetch the currently authenticated user's profile. */
    getCurrentUser: function () {
      return request("/auth/me", { auth: true });
    },

    /** Forget the stored token (client-side logout). */
    logout: function () {
      clearToken();
    },

    /** List the current user's roles (job applications), newest first. */
    listRoles: function () {
      return request("/roles", { auth: true });
    },

    /** Fetch a single role by id. */
    getRole: function (roleId) {
      return request("/roles/" + roleId, { auth: true });
    },

    /** Fetch the most recent draft for a role (used for polling + final display). */
    getRoleDraft: function (roleId) {
      return request("/roles/" + roleId + "/draft", { auth: true });
    },

    /** Fetch a single draft by id. */
    getDraft: function (draftId) {
      return request("/drafts/" + draftId, { auth: true });
    },

    /**
     * Create a role from a resume PDF + JD and start the generation pipeline.
     * @param {object} fields  { jobTitle, company, jdText, file }.
     * @returns {Promise<object>}  { role, draft_id, status }.
     */
    createRole: function (fields) {
      var formData = new FormData();
      formData.append("job_title", fields.jobTitle);
      formData.append("company", fields.company);
      // Send whichever JD source the user gave; the backend scrapes a URL when
      // no text is supplied.
      if (fields.jdText) formData.append("jd_text", fields.jdText);
      if (fields.jdUrl) formData.append("jd_url", fields.jdUrl);
      formData.append("resume_pdf", fields.file);
      return request("/roles", { method: "POST", form: formData, auth: true });
    },

    /** Update a role's user-managed application status. */
    updateRoleStatus: function (roleId, applicationStatus) {
      return request("/roles/" + roleId, {
        method: "PATCH",
        body: { application_status: applicationStatus },
        auth: true
      });
    },

    /** Delete a single role (its drafts cascade away). */
    deleteRole: function (roleId) {
      return request("/roles/" + roleId, { method: "DELETE", auth: true });
    },

    /** Delete several roles at once; resolves with the ids actually deleted. */
    bulkDeleteRoles: function (ids) {
      return request("/roles/bulk-delete", { method: "POST", body: { ids: ids }, auth: true });
    },

    /** Re-run a single agent ("resume" | "cover" | "interview") for a role. */
    regenerateArtifact: function (roleId, artifact) {
      return request("/roles/" + roleId + "/regenerate/" + artifact, { method: "POST", auth: true });
    },

    /** Download the cover letter as a .docx Blob. */
    downloadCoverLetterDocx: function (roleId) {
      return requestBlob("/roles/" + roleId + "/export/cover-letter.docx");
    },

    /** Download the rewritten resume as a .pdf Blob. */
    downloadResumePdf: function (roleId) {
      return requestBlob("/roles/" + roleId + "/export/resume.pdf");
    },

    /** ATS keyword score for the rewritten resume. */
    atsScore: function (roleId) {
      return request("/roles/" + roleId + "/ats-score", { method: "POST", auth: true });
    },

    /** Grade a transcribed spoken interview answer. */
    gradeInterviewAnswer: function (roleId, payload) {
      return request("/roles/" + roleId + "/interview/grade", { method: "POST", body: payload, auth: true });
    },

    /** Two salary-negotiation scripts for an offer. */
    salaryCoach: function (roleId, offeredSalary) {
      return request("/roles/" + roleId + "/salary-coach", { method: "POST", body: { offered_salary: offeredSalary }, auth: true });
    },

    /** Download a 1-week follow-up .ics calendar event. */
    downloadFollowupIcs: function (roleId) {
      return requestBlob("/roles/" + roleId + "/export/calendar");
    }
  };

  window.API = API;
})();
