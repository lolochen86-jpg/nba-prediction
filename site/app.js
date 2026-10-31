(() => {
  'use strict';
  const en = document.documentElement.lang === 'en';
  const say = (zh, english) => en ? english : zh;
  const builtAt = window.HOOPSLAB_BUILT_AT;
  const dataURL = new URL(en ? '../data/app.json' : 'data/app.json', location.href);
  const workflowURL = 'https://github.com/lolochen86-jpg/nba-prediction/actions/workflows/update.yml';
  const apiURL = 'https://api.github.com/repos/lolochen86-jpg/nba-prediction/actions/workflows/update.yml/runs?branch=main&per_page=1';

  document.querySelectorAll('[data-language]').forEach(link => {
    link.addEventListener('click', () => {
      try { localStorage.setItem('hoopslab-language', link.dataset.language); } catch (_) {}
    });
  });
  try {
    if (!en && localStorage.getItem('hoopslab-language') === 'en') {
      location.replace(document.getElementById('langEn').href);
      return;
    }
  } catch (_) {}
  document.getElementById('reloadBtn')?.addEventListener('click', () => location.reload());

  const stale = document.getElementById('staleBar');
  const age = (Date.now() - new Date(builtAt).getTime()) / 36e5;
  if (stale && age >= 12) {
    stale.textContent = say(
      `⚠ 這份資料已超過 ${Math.floor(age)} 小時，傷病與賽程可能已變動。請用「手動更新資料」重新抓取資料。`,
      `⚠ This snapshot is ${Math.floor(age)} hours old. Injuries and schedules may have changed. Use “Update data” to start a fresh build.`
    );
    stale.hidden = false;
  }

  const button = document.getElementById('manualUpdateBtn');
  const panel = document.getElementById('manualUpdatePanel');
  const status = document.getElementById('updateStatus');
  const runLink = document.getElementById('workflowRunLink');
  let polling = null;
  let openedAt = 0;
  let checking = false;

  async function checkUpdate() {
    if (checking || document.hidden || panel.hidden) return;
    checking = true;
    try {
      // Only a changed snapshot means new data is actually available on this site.
      const response = await fetch(dataURL, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Site HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.updated_utc && new Date(payload.updated_utc) > new Date(builtAt)) {
        status.textContent = say(`新資料已上線：${payload.updated_tpe}（台灣時間）。`, `New data is live: ${payload.updated_tpe} (Taipei).`);
        let reload = document.getElementById('loadUpdatedData');
        if (!reload) {
          reload = document.createElement('button');
          reload.id = 'loadUpdatedData';
          reload.className = 'btn-ghost primary';
          reload.textContent = say('載入新資料', 'Load new data');
          reload.addEventListener('click', () => location.reload());
          status.after(reload);
        }
        clearInterval(polling);
        return;
      }
      const result = await fetch(apiURL, { headers: { Accept: 'application/vnd.github+json' } });
      if (!result.ok) throw new Error(`GitHub HTTP ${result.status}`);
      const runs = (await result.json()).workflow_runs || [];
      const run = runs[0];
      if (!run) {
        status.textContent = say('尚無執行紀錄。請到 GitHub 按 Run workflow 啟動更新。', 'No runs yet. Open GitHub and select Run workflow to start an update.');
        return;
      }
      // Only link to the expected GitHub repository, even if an API response is malformed.
      if (typeof run.html_url === 'string' && run.html_url.startsWith('https://github.com/lolochen86-jpg/nba-prediction/actions/runs/')) {
        runLink.href = run.html_url;
      } else runLink.href = workflowURL;
      const when = new Date(run.created_at).toLocaleString(en ? 'en-GB' : 'zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
      const prefix = say(`最近一次執行（${when} 台灣時間）：`, `Latest run (${when} Taipei): `);
      const states = {
        queued: say('排隊中', 'Queued'),
        requested: say('等待執行', 'Requested'),
        waiting: say('等待執行', 'Waiting'),
        pending: say('等待執行', 'Pending'),
        in_progress: say('更新中：抓取、驗證及部署資料', 'Running: fetching, validating and deploying data'),
      };
      if (run.status === 'completed') {
        status.textContent = prefix + (run.conclusion === 'success'
          ? say(`流程成功。目前本站資料時間為 ${payload.updated_tpe}（台灣時間）。`, `Workflow succeeded. The current site snapshot is ${payload.updated_tpe} (Taipei).`)
          : say(`未成功（${run.conclusion || 'unknown'}）。請查看執行紀錄。`, `Not successful (${run.conclusion || 'unknown'}). View the run logs.`));
      } else status.textContent = prefix + (states[run.status] || say('請查看執行紀錄。', 'View the run logs.'));
    } catch (_) {
      status.textContent = say('暫時無法讀取狀態；請開啟執行紀錄確認。', 'Status is temporarily unavailable. Open the run logs to check.');
    } finally { checking = false; }
  }
  button?.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    button.setAttribute('aria-expanded', String(!panel.hidden));
    clearInterval(polling);
    if (!panel.hidden) {
      openedAt = Date.now();
      checkUpdate();
      polling = setInterval(() => {
        if (Date.now() - openedAt > 30 * 60000) return clearInterval(polling);
        checkUpdate();
      }, 60000);
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !panel.hidden) checkUpdate();
  });
})();
