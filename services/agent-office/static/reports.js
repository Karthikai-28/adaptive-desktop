// Agent Office — the daily reports on the desktop: the 10:00 standup and the 19:00 evening summary
// (office/reports.py makes them on schedule; Asia/Kolkata by default), and reports made on demand.
// The same list and words as the phone's Reports screen.

const STATUS_CLASS = { generated: 'running', delivered: 'done', missed: 'cancelled', failed: 'failed' };
const KIND_LABEL = { standup: 'Standup', evening: 'Evening summary' };

export function createReports(ctx) {
  const { h, api, toast, openModal, modalKind, md } = ctx;
  const R = { lists: new Set(), id: null };

  const row = (r) => h('button', { class: 'rp-row', onclick: () => openReport(r.id) },
    h('span', { class: 'rp-main' }, h('b', null, r.title || KIND_LABEL[r.kind]),
      h('small', null, r.summary || (r.status === 'missed' ? 'Missed: the office was not running, and a later report covered it.' : r.error || ''))),
    h('span', { class: `pill ${STATUS_CLASS[r.status] || ''}` }, r.manual ? 'on demand' : r.status));

  async function list(el, { limit = 8 } = {}) {
    el._reports = { limit };
    R.lists.add(el);
    try {
      const [sched, rows] = await Promise.all([api('GET', '/api/reports/schedule'), api('GET', `/api/reports?limit=${limit}`)]);
      const next = Object.entries(sched.kinds || {}).map(([k, v]) => `${KIND_LABEL[k]} ${v.time} (next ${v.next_local})`).join(' · ');
      el.replaceChildren(
        h('p', { class: 'tk-note', style: 'margin:0 0 8px' }, sched.enabled ? `${next} · ${sched.timezone}` : 'Scheduled reports are turned off in config.json.'),
        ...(rows.length ? rows.filter(r => r.status !== 'missed' || rows.length < 4).map(row) : [h('div', { class: 'empty' }, 'No reports yet. The first one is made at the next scheduled time.')]));
    } catch (e) { el.replaceChildren(h('div', { class: 'empty' }, `Couldn't read the reports: ${e.message}`)); }
  }

  async function generate(kind, btn) {
    if (btn) btn.disabled = true;
    try { const r = await api('POST', '/api/reports/generate', { kind }); toast(`${KIND_LABEL[kind]} made`, 'ok'); openReport(r.id); }
    catch (e) { toast(e.message, 'error'); }
    finally { if (btn) btn.disabled = false; }
  }
  const nowButtons = () => [
    h('button', { class: 'act', style: 'flex:none;padding:0 14px', onclick: (e) => generate('standup', e.currentTarget) }, 'Standup now'),
    h('button', { class: 'act', style: 'flex:none;padding:0 14px', onclick: (e) => generate('evening', e.currentTarget) }, 'Summary now')];

  function open() {
    const box = h('div');
    openModal('reports', 'Daily reports', h('div', null,
      h('p', { class: 'tk-note', style: 'margin:0 0 12px' }, 'Made by the office on schedule, also while you are away; a time it missed is made once it runs again, marked catch-up. "Now" makes an extra one; it does not change the schedule.'),
      box), nowButtons());
    list(box, { limit: 60 });
  }

  async function openReport(id) {
    R.id = id;
    let r;
    try { r = await api('GET', `/api/reports/${id}`); } catch (e) { return toast(e.message, 'error'); }
    if (R.id !== id) return;
    const facts = [r.manual ? 'on demand' : r.catch_up ? `catch-up for ${r.scheduled_at_local}` : `scheduled ${r.scheduled_at_local}`,
      `covers ${r.window_start_local} to ${r.window_end_local}`, r.delivered_at_local ? `delivered to the phone ${r.delivered_at_local}` : r.status === 'generated' ? 'not yet delivered to the phone' : ''];
    openModal('report', r.title, h('div', null,
      h('p', { class: 'tk-note', style: 'margin:0 0 12px' }, `${facts.filter(Boolean).join(' · ')} · ${r.timezone}`),
      r.markdown ? h('div', { class: 'md rp-body', html: md(r.markdown.replace(/^# .*\n+/, '')) }) : h('div', { class: 'box err' }, r.error || 'This report has no text.')),
      [h('button', { class: 'act', style: 'flex:none;padding:0 14px', onclick: open }, 'All reports')], true);
    R.id = id;
  }

  let timer = null;
  function changed() {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      for (const el of [...R.lists]) { if (!el.isConnected) { R.lists.delete(el); continue; } list(el, el._reports); }
    }, 600);
  }
  return { list, open, openReport, changed, nowButtons, isOpen: () => modalKind() === 'reports' };
}
