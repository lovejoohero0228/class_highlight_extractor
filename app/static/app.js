const fileInput = document.getElementById("fileInput");
const uploadButton = document.getElementById("uploadButton");
const uploadStatus = document.getElementById("uploadStatus");
const customPrompt = document.getElementById("customPrompt");
const clipShape = document.getElementById("clipShape");
const currentGroups = document.getElementById("currentGroups");
const archivedGroups = document.getElementById("archivedGroups");
const requestGroupTemplate = document.getElementById("requestGroupTemplate");
const jobTemplate = document.getElementById("jobTemplate");
const clipTemplate = document.getElementById("clipTemplate");
const topTabs = [...document.querySelectorAll(".top-tab")];
const topPanels = [...document.querySelectorAll(".top-panel")];

const clipTabState = new Map();
const mergeSelectionByJob = new Map();
let lastJobsDigest = "";

function formatSeconds(value) {
  const total = Math.max(0, Math.floor(value || 0));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function setEmptyState(container, message) {
  container.innerHTML = `<div class="empty-state">${message}</div>`;
}

function normalizeVideoGroupKey(filename) {
  const raw = String(filename || "").trim().toLowerCase();
  if (!raw) return "__unknown__";
  const withoutExt = raw.replace(/\.[a-z0-9]{2,5}$/i, "");
  const withoutCopySuffix = withoutExt
    .replace(/\s*\(\d+\)\s*$/g, "")
    .replace(/\s*-\s*copy(?:\s*\d+)?\s*$/g, "")
    .replace(/\s*copy(?:\s*\d+)?\s*$/g, "");
  return withoutCopySuffix.replace(/\s+/g, " ").trim() || "__unknown__";
}

function normalizeReasonText(reason) {
  const raw = String(reason || "").trim();
  if (!raw) return "설명 정보가 없습니다.";
  const withoutTimestamps = raw.replace(/\[[0-9.]+\s*-\s*[0-9.]+\]\s*/g, "");
  const lines = withoutTimestamps.split(/\n+/).map((item) => item.trim()).filter(Boolean);
  const seen = new Set();
  const deduped = [];
  for (const line of lines) {
    const key = line.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(line);
  }
  return deduped.join("\n");
}

function getStatusLabel(status) {
  if (status === "uploaded") return "업로드됨";
  if (status === "processing") return "처리 중";
  if (status === "completed") return "완료";
  if (status === "failed") return "실패";
  return status || "";
}

function computeJobsDigest(jobs) {
  return JSON.stringify(
    jobs.map((job) => ({
      job_id: job.job_id,
      status: job.status,
      progress: job.progress,
      message: job.message,
      updated_at: job.updated_at,
      clip_count: (job.clips || []).length,
      clip_keys: (job.clips || []).map((clip) => `${clip.clip_id}:${clip.clip_status}:${clip.confidence_score}`),
      archived: job.archived,
    })),
  );
}

function groupJobs(jobs) {
  const groups = new Map();
  for (const job of jobs) {
    const groupId = job.request_group_id || `group-${job.job_id}`;
    if (!groups.has(groupId)) {
      groups.set(groupId, {
        request_group_id: groupId,
        request_label: job.request_label || "업로드 요청",
        created_at: job.created_at,
        archived: Boolean(job.archived),
        jobs: [],
      });
    }
    const group = groups.get(groupId);
    group.jobs.push(job);
    if (!group.created_at || new Date(job.created_at) < new Date(group.created_at)) {
      group.created_at = job.created_at;
    }
  }
  return [...groups.values()].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
}

function groupJobsByFile(jobs) {
  const fileMap = new Map();
  for (const job of jobs) {
    const fileName = (job.video?.original_filename || "").trim() || "파일명 없음";
    const fileKey = normalizeVideoGroupKey(fileName);
    if (!fileMap.has(fileKey)) {
      fileMap.set(fileKey, {
        file_key: fileKey,
        file_name: fileName,
        latest_created_at: job.created_at,
        request_groups: [],
      });
    }
    const fileGroup = fileMap.get(fileKey);
    if (!fileGroup.latest_created_at || new Date(job.created_at || 0) > new Date(fileGroup.latest_created_at || 0)) {
      fileGroup.latest_created_at = job.created_at;
      fileGroup.file_name = fileName;
    }
    fileGroup.request_groups.push(job);
  }

  const groupedFiles = [];
  for (const item of fileMap.values()) {
    item.request_groups = groupJobs(item.request_groups)
      .sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
    groupedFiles.push(item);
  }

  return groupedFiles.sort((a, b) => new Date(b.latest_created_at || 0) - new Date(a.latest_created_at || 0));
}

function applyClipTab(node, selectedTab) {
  const buttons = [...node.querySelectorAll(".tab-button")];
  const panels = [...node.querySelectorAll(".tab-panel")];
  for (const item of buttons) item.classList.toggle("active", item.dataset.tab === selectedTab);
  for (const panel of panels) panel.classList.toggle("active", panel.dataset.panel === selectedTab);
}

function wireTabs(node, clipId) {
  const buttons = [...node.querySelectorAll(".tab-button")];
  const initialTab = clipTabState.get(clipId) || "transcript";
  applyClipTab(node, initialTab);
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const selected = button.dataset.tab || "transcript";
      clipTabState.set(clipId, selected);
      applyClipTab(node, selected);
    });
  }
}

function setJobSelection(jobId, clipId, checked) {
  if (!mergeSelectionByJob.has(jobId)) {
    mergeSelectionByJob.set(jobId, new Set());
  }
  const selected = mergeSelectionByJob.get(jobId);
  if (checked) selected.add(clipId);
  else selected.delete(clipId);
}

function getJobSelection(jobId) {
  if (!mergeSelectionByJob.has(jobId)) {
    mergeSelectionByJob.set(jobId, new Set());
  }
  return mergeSelectionByJob.get(jobId);
}

async function mergeSelectedClips(job, statusNode, buttonNode) {
  const selected = [...getJobSelection(job.job_id)];
  if (selected.length < 2) {
    statusNode.textContent = "두 개 이상의 클립을 선택해주세요.";
    return;
  }

  buttonNode.disabled = true;
  statusNode.textContent = "선택 클립을 합치고 있습니다...";
  try {
    const response = await fetch(`/api/jobs/${job.job_id}/merge-download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_ids: selected }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({ detail: "병합 다운로드에 실패했습니다." }));
      statusNode.textContent = data.detail || "병합 다운로드에 실패했습니다.";
      return;
    }

    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `dearsunshine_merged_${job.job_id}.mp4`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
    statusNode.textContent = "병합 영상 다운로드를 시작했습니다.";
  } finally {
    buttonNode.disabled = false;
  }
}

function renderClip(clip, job) {
  const node = clipTemplate.content.firstElementChild.cloneNode(true);
  const selected = getJobSelection(job.job_id);

  node.querySelector(".activity-badge").textContent = clip.activity_type;
  node.querySelector(".confidence-text").textContent = `신뢰도 ${Math.round((clip.confidence_score || 0) * 100)}%`;
  node.querySelector("video").src = clip.preview_url;
  node.querySelector(".clip-range").textContent = `${formatSeconds(clip.clip_start)} - ${formatSeconds(clip.clip_end)} (${formatSeconds(clip.clip_duration)})`;
  node.querySelector(".transcript-text").textContent = clip.transcript_excerpt || "이 구간의 대본 요약이 없습니다.";
  node.querySelector(".explain-text").textContent = normalizeReasonText(clip.explain_text);

  const checkbox = node.querySelector(".merge-checkbox");
  checkbox.checked = selected.has(clip.clip_id);
  checkbox.addEventListener("change", () => {
    setJobSelection(job.job_id, clip.clip_id, checkbox.checked);
  });

  const downloadLink = node.querySelector(".download-link");
  downloadLink.href = clip.download_url;

  const deleteButton = node.querySelector(".delete-button");
  deleteButton.addEventListener("click", async () => {
    deleteButton.disabled = true;
    const response = await fetch(`/api/clips/${clip.clip_id}`, { method: "DELETE" });
    if (response.ok) {
      setJobSelection(job.job_id, clip.clip_id, false);
      await refreshJobs(true);
    } else {
      deleteButton.disabled = false;
    }
  });

  wireTabs(node, clip.clip_id);
  return node;
}

function renderJob(job) {
  const node = jobTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".job-name").textContent = job.video.original_filename;
  node.querySelector(".job-status").textContent = getStatusLabel(job.status);
  node.querySelector(".progress-bar").style.width = `${job.progress || 0}%`;
  node.querySelector(".job-message").textContent = job.message || "";
  node.querySelector(".job-error").textContent = job.error || "";

  const mergeButton = node.querySelector(".merge-button");
  const mergeStatus = node.querySelector(".merge-status");
  mergeButton.addEventListener("click", async () => {
    await mergeSelectedClips(job, mergeStatus, mergeButton);
  });

  const clipContainer = node.querySelector(".video-clips");
  const visibleClips = (job.clips || []).filter((clip) => clip.clip_status !== "deleted");
  if (!visibleClips.length) {
    clipContainer.innerHTML = `<div class="empty-state">이 영상에 표시할 클립이 없습니다.</div>`;
    mergeButton.disabled = true;
    return node;
  }

  const grid = document.createElement("div");
  grid.className = "clips-grid";
  for (const clip of visibleClips) grid.appendChild(renderClip(clip, job));
  clipContainer.appendChild(grid);
  return node;
}

function renderGroup(group) {
  const node = requestGroupTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".request-label").textContent = group.request_label || "업로드 요청";
  node.querySelector(".request-title").textContent = `요청 그룹 ${group.request_group_id.slice(-8)}`;
  node.querySelector(".request-badge").textContent = group.archived ? "Archived" : "현재";
  node.querySelector(".request-meta").textContent = `생성 시각 ${formatDateTime(group.created_at)} · 영상 ${group.jobs.length}개`;

  const stack = node.querySelector(".video-stack");
  for (const job of group.jobs.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0))) {
    stack.appendChild(renderJob(job));
  }
  return node;
}

function renderGroups(container, groups, emptyMessage) {
  renderFileGroups(container, groups, emptyMessage);
}

function renderRequestItem(group, requestIndex) {
  const item = document.createElement("details");
  item.className = "request-item";
  if (requestIndex === 0) item.open = true;

  const summary = document.createElement("summary");
  summary.className = "request-item-summary";

  const left = document.createElement("div");
  left.className = "request-item-title";
  const title = document.createElement("strong");
  title.textContent = `요청 ${requestIndex + 1}`;
  const label = document.createElement("span");
  label.textContent = group.request_label || "요청";
  left.append(title, label);

  const meta = document.createElement("span");
  meta.className = "request-item-meta";
  meta.textContent = `${formatDateTime(group.created_at)} · 영상 ${group.jobs.length}개`;
  summary.append(left, meta);

  const body = document.createElement("div");
  body.className = "request-item-body";
  const stack = document.createElement("div");
  stack.className = "video-stack";
  for (const job of group.jobs.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0))) {
    stack.appendChild(renderJob(job));
  }
  body.appendChild(stack);

  item.append(summary, body);
  return item;
}

function renderFileGroups(container, fileGroups, emptyMessage) {
  if (!fileGroups.length) {
    setEmptyState(container, emptyMessage);
    return;
  }

  container.innerHTML = "";
  for (const fileGroup of fileGroups) {
    const node = document.createElement("article");
    node.className = "file-group";

    const header = document.createElement("div");
    header.className = "file-group-header";
    const title = document.createElement("h3");
    title.className = "file-group-title";
    title.textContent = fileGroup.file_name;
    const badge = document.createElement("span");
    badge.className = "request-badge";
    badge.textContent = `요청 ${fileGroup.request_groups.length}개`;
    header.append(title, badge);

    const requestList = document.createElement("div");
    requestList.className = "file-request-list";
    fileGroup.request_groups.forEach((group, index) => {
      requestList.appendChild(renderRequestItem(group, index));
    });

    node.append(header, requestList);
    container.appendChild(node);
  }
}

async function uploadFiles(files) {
  if (!files.length) {
    uploadStatus.textContent = "업로드할 영상을 먼저 선택해주세요.";
    return;
  }

  const now = new Date();
  const requestGroupId = `request_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  const requestLabel = `${new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(now)} 업로드`;

  uploadButton.disabled = true;
  uploadStatus.textContent = `${files.length}개 파일을 업로드하고 있습니다...`;

  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    form.append("request_group_id", requestGroupId);
    form.append("request_label", requestLabel);
    form.append("custom_prompt", customPrompt.value.trim());
    form.append("clip_shape", clipShape.value);

    const response = await fetch("/api/videos", { method: "POST", body: form });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "업로드에 실패했습니다." }));
      uploadStatus.textContent = error.detail || "업로드에 실패했습니다.";
      uploadButton.disabled = false;
      return;
    }
  }

  uploadStatus.textContent = "업로드가 등록되었습니다. 같은 요청 그룹으로 묶어 처리합니다.";
  fileInput.value = "";
  uploadButton.disabled = false;
  await refreshJobs(true);
}

async function refreshJobs(forceRender = false) {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    uploadStatus.textContent = "작업 목록을 불러오지 못했습니다.";
    return;
  }

  const jobs = await response.json();
  const digest = computeJobsDigest(jobs);
  if (!forceRender && digest === lastJobsDigest) {
    return;
  }
  lastJobsDigest = digest;

  const current = groupJobsByFile(jobs.filter((job) => !job.archived));
  const archived = groupJobsByFile(jobs.filter((job) => job.archived));

  renderGroups(currentGroups, current, "현재 실행에서 생성되거나 진행 중인 요청이 없습니다.");
  renderGroups(archivedGroups, archived, "보관된 과거 결과가 없습니다.");
}

uploadButton.addEventListener("click", async () => {
  await uploadFiles([...fileInput.files]);
});

fileInput.addEventListener("change", () => {
  uploadStatus.textContent = fileInput.files.length ? `${fileInput.files.length}개 파일이 선택되었습니다.` : "";
});

for (const tab of topTabs) {
  tab.addEventListener("click", () => {
    const selected = tab.dataset.topTab;
    for (const item of topTabs) item.classList.toggle("active", item === tab);
    for (const panel of topPanels) panel.classList.toggle("active", panel.dataset.topPanel === selected);
  });
}

setInterval(refreshJobs, 3000);
refreshJobs(true);
