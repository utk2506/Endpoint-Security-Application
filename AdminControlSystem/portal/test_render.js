const info = {
  "os_arch": "64-bit",
  "network": [
    {
      "description": "Intel(R) Wireless-AC 9560",
      "mac": "34:7D:F6:CC:52:40",
      "ip": "192.168.1.8"
    }
  ],
  "uptime": "28h 57m",
  "bios_version": "1.36.0",
  "os_version": "10.0.19045",
  "cpu_name": "Intel(R) Core(TM) i3-8145U CPU @ 2.10GHz",
  "model": "Latitude 3400",
  "disks": [
    {
      "drive": "C:",
      "size_gb": 237.83,
      "free_gb": 30.4
    }
  ],
  "ram_free_gb": 3.68,
  "cpu_cores": 2,
  "hostname": "ITSUPPORT",
  "cpu_load_pct": 52,
  "serial_number": "H31K103",
  "ram_used_pct": 76.8,
  "logged_user": "AzureAD\\ITSupport",
  "os_name": "Microsoft Windows 10 Pro",
  "manufacturer": "Dell Inc.",
  "ram_total_gb": 15.88
};

function renderSysInfo(info) {
    const pct = (v, total) => {
        const p = total > 0 ? Math.min(100, Math.round((v / total) * 100)) : 0;
        const color = p > 85 ? '#ef4444' : p > 60 ? '#f59e0b' : '#10b981';
        return `<div class="sysinfo-bar-wrap">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-secondary);margin-bottom:3px;">
                <span>${p}% used</span><span>${(total - v).toFixed(1)} free</span>
            </div>
            <div class="sysinfo-bar-track"><div class="sysinfo-bar-fill" style="width:${p}%;background:${color};"></div></div>
        </div>`;
    };

    const row = (label, value) => `
        <div class="sysinfo-row">
            <span class="sysinfo-label">${label}</span>
            <span class="sysinfo-value">${value ?? '—'}</span>
        </div>`;

    const ramUsed = (info.ram_total_gb || 0) - (info.ram_free_gb || 0);

    // Disks
    const disks = Array.isArray(info.disks) ? info.disks : (info.disks ? [info.disks] : []);
    const disksHtml = disks.map(d => `
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">💾 Storage — ${d.drive}</div>
            ${row('Total', `${d.size_gb} GB`)}
            ${row('Free', `${d.free_gb} GB`)}
            ${pct(d.size_gb - d.free_gb, d.size_gb)}
        </div>`).join('');

    // Network
    const nics = Array.isArray(info.network) ? info.network : (info.network ? [info.network] : []);
    const nicsHtml = nics.map(n => `
        ${row(n.description || 'Adapter', `${n.ip || '—'} (${n.mac || '—'})`)}`).join('');

    return `<div class="sysinfo-grid">
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🖥️ System</div>
            ${row('Hostname', info.hostname)}
            ${row('Logged-in User', info.logged_user)}
            ${row('Manufacturer', info.manufacturer)}
            ${row('Model', info.model)}
            ${row('Serial', info.serial_number)}
            ${row('BIOS', info.bios_version)}
            ${row('Uptime', info.uptime)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">⚙️ OS</div>
            ${row('OS Name', info.os_name)}
            ${row('Version', info.os_version)}
            ${row('Architecture', info.os_arch)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🧠 CPU</div>
            ${row('Processor', info.cpu_name)}
            ${row('Cores', info.cpu_cores)}
            ${row('Current Load', info.cpu_load_pct != null ? `${info.cpu_load_pct}%` : '—')}
            ${pct(info.cpu_load_pct || 0, 100)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🗄️ RAM</div>
            ${row('Total RAM', `${info.ram_total_gb} GB`)}
            ${row('Used RAM', `${ramUsed.toFixed(2)} GB`)}
            ${row('Free RAM', `${(info.ram_free_gb || 0).toFixed(2)} GB`)}
            ${pct(ramUsed, info.ram_total_gb || 1)}
        </div>
        ${disksHtml}
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">🌐 Network</div>
            ${nicsHtml || row('Status', 'No active adapters found')}
        </div>
    </div>`;
}

try {
    console.log(renderSysInfo(info));
} catch (e) {
    console.error(e);
}
