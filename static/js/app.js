// Sales Dialer POC - Main Application
// Using Twilio Voice SDK 2.x + WebSocket for real-time updates

let device = null;
let currentCall = null;
let campaign = null;
let websocket = null;
let isMuted = false;
let currentConnectedPhone = null;
let agentName = null;
let selectedCampaignId = null;
let visibleContacts = [];
let callHistoryByPhone = {};
let answeredPhones = new Set();
let historyCampaignId = null;

// DOM Elements
let statusIndicator, statusText, agentInfo, agentNameDisplay, startCampaignBtn, endCampaignBtn, muteBtn;
let contactListContainer, contactList, contactCount, logContainer;
let callHistoryContainer, callHistoryList, callHistoryCount;
let dispositionModal, dispositionPhone, dispositionSelect, dispositionNotes;
let agentNameModal, agentNameInput, campaignSelect;

// ============== Utility Functions ==============

function log(message, type = 'info') {
    if (!logContainer) {
        console.log(`[${type.toUpperCase()}] ${message}`);
        return;
    }
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    const timestamp = new Date().toLocaleTimeString();
    entry.textContent = `[${timestamp}] ${message}`;
    logContainer.insertBefore(entry, logContainer.firstChild);
    console.log(`[${type.toUpperCase()}] ${message}`);
}

function updateStatus(status, info = '') {
    if (!statusIndicator || !statusText) return;
    
    statusIndicator.className = `status-indicator ${status}`;
    
    const statusMessages = {
        'idle': 'Idle',
        'connecting': 'Connecting...',
        'ready': 'Waiting for Leads',
        'on-call': 'On Call',
        'connected': 'Lead Connected!',
        'error': 'Error'
    };
    
    statusText.textContent = statusMessages[status] || status;
    if (info && agentInfo) {
        agentInfo.textContent = info;
    }
}

// ============== Agent Name ==============

window.setAgentName = function() {
    const name = agentNameInput.value.trim();
    if (!name) {
        alert('Please enter your name');
        return;
    }
    
    const campaignId = campaignSelect.value;
    if (!campaignId) {
        alert('Please select a campaign');
        return;
    }
    
    agentName = name;
    selectedCampaignId = parseInt(campaignId);
    agentNameModal.style.display = 'none';
    agentNameDisplay.textContent = `Agent: ${agentName}`;
    log(`Agent name set: ${agentName}`, 'success');
    log(`Campaign selected: ${campaignSelect.options[campaignSelect.selectedIndex].text}`, 'success');
    
    // Connect WebSocket
    connectWebSocket(agentName);
}

// ============== Mute Toggle ==============

window.toggleMute = function() {
    if (!currentCall) {
        log('No active call to mute', 'error');
        return;
    }
    
    isMuted = !isMuted;
    currentCall.mute(isMuted);
    
    if (isMuted) {
        muteBtn.textContent = '🔇 Unmute';
        muteBtn.classList.add('muted');
        log('Microphone muted');
    } else {
        muteBtn.textContent = '🎤 Mute';
        muteBtn.classList.remove('muted');
        log('Microphone unmuted');
    }
};

// ============== Disposition Modal ==============

function showDispositionModal(phone) {
    currentConnectedPhone = phone;
    dispositionPhone.textContent = `Call ended with: ${phone}`;
    dispositionSelect.value = 'interested';
    dispositionNotes.value = '';
    dispositionModal.style.display = 'flex';
}

function hideDispositionModal() {
    dispositionModal.style.display = 'none';
}

window.submitDisposition = async function(callNext) {
    const disposition = dispositionSelect.value;
    const notes = dispositionNotes.value;
    
    log(`Disposition for ${currentConnectedPhone}: ${disposition}`, 'success');
    
    // Send disposition to backend
    if (campaign && campaign.id) {
        try {
            await fetch(`/api/campaign/${campaign.id}/disposition`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    phone: currentConnectedPhone,
                    disposition: disposition,
                    notes: notes
                })
            });
        } catch (error) {
            console.error('Error saving disposition:', error);
        }
    }
    
    hideDispositionModal();
    
    if (callNext) {
        // Dial next batch
        await dialNextBatch();
    } else {
        log('Waiting for next action...', 'info');
        updateStatus('ready', 'Ready for next call');
    }
};

async function dialNextBatch() {
    if (!agentName) {
        log('No agent name', 'error');
        return;
    }

    if (!campaign || !campaign.queue_name) {
        log('No active campaign or queue name', 'error');
        return;
    }

    log('Connecting to agent queue and dialing next batch...');

    try {
        // First, connect agent back to the agent queue
        updateStatus('connecting', 'Connecting to agent queue...');
        await connectToAgentQueue(campaign.queue_name);

        // Then dial the next batch
        log('Dialing next batch...');
        const response = await fetch(`/api/agent/${encodeURIComponent(agentName)}/dial-next-batch`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();
            if (data.phones && data.phones.length > 0) {
                log(`Calling ${data.count} contacts...`, 'success');
                // No "Next Batch" UI (agent has a fixed assigned pool)
            } else {
                log('No more contacts to dial', 'info');
                // Don't update the UI here - let the campaign_updated message handle it
                // The campaign_updated message will show the correct next batch state
            }
        }
    } catch (error) {
        console.error('Error in dial next batch flow:', error);
        log(`Error: ${error.message}`, 'error');
        updateStatus('ready', 'Ready for next call');
    }
}

// ============== WebSocket ==============

function connectWebSocket(agentName) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${encodeURIComponent(agentName)}`;
    
    log(`Connecting to WebSocket...`);
    websocket = new WebSocket(wsUrl);
    
    websocket.onopen = function() {
        log('WebSocket connected', 'success');
    };
    
    websocket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    websocket.onclose = function() {
        log('WebSocket disconnected');
    };
    
    websocket.onerror = function(error) {
        console.error('WebSocket error:', error);
        log('WebSocket error', 'error');
    };
}

function handleWebSocketMessage(data) {
    console.log('WebSocket message:', data);
    
    switch (data.type) {
        case 'agent_state':
            if (data.campaign) {
                campaign = data.campaign;
                updateContactStatus(data.campaign.contact_status);
            }
            break;
            
        case 'status_update':
            log(`${data.phone}: ${formatStatus(data.status)}`);
            updateContactStatus(data.contact_status);
            break;
            
        case 'call_queued':
            log(`📞 ${data.phone} answered and queued`, 'success');
            updateContactStatus(data.contact_status || {});
            break;
            
        case 'customer_connected':
            currentConnectedPhone = data.phone;
            log(`🎉 ${data.phone} connected!`, 'success');
            updateStatus('connected', `Speaking with ${data.phone}`);
            updateContactStatus(data.campaign.contact_status);
            // Show mute button when on call
            if (muteBtn) muteBtn.style.display = 'inline-block';
            break;

        case 'campaign_updated':
            // Update campaign data and refresh contact list
            if (data.campaign) {
                console.log('=== CAMPAIGN UPDATED ===');
                console.log('Campaign:', {
                    contacts: data.campaign.contacts,
                    is_recycling: data.campaign.is_recycling
                });

                // Process UI update immediately
                try {
                    console.log('Current campaign before update:', JSON.stringify(campaign, null, 2));
                    const oldCampaign = {...campaign};
                    campaign = data.campaign;
                    console.log('Campaign updated to:', JSON.stringify(campaign, null, 2));

                    console.log('Calling displayContacts...');
                    displayContacts(data.campaign);
                    console.log('displayContacts completed');
                    log(`Campaign updated: contacts=${data.campaign.contacts.length}`, 'info');
                    console.log('=== CAMPAIGN UPDATE COMPLETE ===');

                } catch (error) {
                    console.error('Error during UI update setup:', error);
                    isUpdatingUI = false;
                }
            } else {
                console.log('ERROR: campaign_updated received without campaign data');
            }
            break;

        case 'customer_ready':
            // Customer is ready - already connected to same queue, Twilio will connect us automatically
            log(`📞 Customer ${data.phone} connected!`, 'success');
            updateStatus('connected', `On call with ${data.phone}`);
            // Show mute button when on call
            if (muteBtn) muteBtn.style.display = 'inline-block';
            break;

        case 'amd_result':
            // Log AMD result (for debugging only)
            log(`🤖 AMD for ${data.phone}: ${data.answered_by} - ${data.machine_detection_status}`);
            console.log('AMD Detection Result:', data.detection_result);
            break;
            
        case 'call_ended':
            // Customer disconnected after being connected - show disposition modal
            log(`Call with ${data.phone} ended`, 'info');
            currentConnectedPhone = null;
            if (muteBtn) muteBtn.style.display = 'none';
            updateStatus('ready', 'Call ended. Ready for next call.');
            updateContactStatus(data.contact_status);
            showDispositionModal(data.phone);
            break;
            
        case 'auto_dial_next':
            // Call failed without connecting - auto-dial next batch
            log(`${data.reason} - dialing next batch...`, 'info');
            // setTimeout(() => dialNextBatch(), 1000); // Disabled automatic dialing
            break;
            
        case 'campaign_ended':
            log('Campaign ended by server');
            // Update contact statuses to show they are ended
            if (data.contact_status) {
                updateContactStatus(data.contact_status);
            }
            break;
    }
}

function disconnectWebSocket() {
    if (websocket) {
        websocket.close();
        websocket = null;
    }
}

// ============== Main Campaign Flow ==============

window.startCampaign = async function() {
    if (!agentName) {
        alert('Please enter your name first');
        agentNameModal.style.display = 'flex';
        return;
    }
    
    startCampaignBtn.disabled = true;
    updateStatus('connecting', 'Starting campaign...');
    log(`Starting campaign for agent ${agentName}...`);

    try {
        // Start campaign
        log('Creating campaign...');
        const campaignResponse = await fetch(`/api/campaign/start?agent_name=${encodeURIComponent(agentName)}&campaign_list_id=${selectedCampaignId}`, {
            method: 'POST'
        });

        if (!campaignResponse.ok) {
            throw new Error('Failed to start campaign');
        }

        const data = await campaignResponse.json();
        campaign = data.campaign;
        const token = data.token;
        const identity = data.identity;
        
        log(`Campaign created: ${campaign.id}`, 'success');
        log(`Token received. Identity: ${identity}`, 'success');
        
        if (campaign.contacts && campaign.contacts.length > 0) {
            log(`Prepared ${campaign.contacts.length} contacts for dialing...`, 'success');
            displayContacts(campaign);
        } else {
            log('No contacts available to dial', 'info');
        }

        // Initialize Twilio Device
        await initializeDevice(token);

        // Connect agent directly to agent queue (will hear hold music until connected)
        log('Connecting to agent queue - waiting for calls...');
        await connectToAgentQueue(campaign.queue_name);

        // Show/hide buttons
        startCampaignBtn.style.display = 'none';
        endCampaignBtn.style.display = 'inline-block';

    } catch (error) {
        console.error('Campaign error:', error);
        log(`Error: ${error.message}`, 'error');
        updateStatus('error', 'Failed to start campaign');
        startCampaignBtn.disabled = false;
        disconnectWebSocket();
    }
};

// ============== Twilio Device ==============

async function initializeDevice(token) {
    if (typeof Twilio === 'undefined' || typeof Twilio.Device === 'undefined') {
        throw new Error('Twilio SDK not loaded. Please refresh the page.');
    }

    log('Initializing Twilio Device...');

    device = new Twilio.Device(token, {
        logLevel: 1,
        codecPreferences: ['opus', 'pcmu'],
        allowIncomingWhileBusy: true
    });

    setupDeviceHandlers();
    await device.register();
    log('Twilio Device registered', 'success');
}

function setupDeviceHandlers() {
    device.on('registered', function() {
        log('Device registered with Twilio');
    });

    device.on('unregistered', function() {
        log('Device unregistered');
        updateStatus('idle', 'Device disconnected');
    });

    device.on('error', function(error) {
        log(`Device error: ${error.message}`, 'error');
        console.error('Twilio Device Error:', error);
    });

    // No incoming calls - agents connect outbound to queue

    device.on('tokenWillExpire', async function() {
        log('Token expiring, refreshing...');
        try {
            const response = await fetch('/api/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            device.updateToken(data.token);
            log('Token refreshed', 'success');
        } catch (error) {
            log(`Failed to refresh token: ${error.message}`, 'error');
        }
    });
}

function setupCallHandlers(call) {
    currentCall = call;

    call.on('accept', function() {
        log('Connected to call from queue!', 'success');
        const message = currentConnectedPhone ? `On call with ${currentConnectedPhone}` : 'On call';
        updateStatus('on-call', message);
        if (muteBtn) muteBtn.style.display = 'inline-block';
    });

    call.on('disconnect', function() {
        log('Disconnected from call');
        currentCall = null;
        if (muteBtn) muteBtn.style.display = 'none';
        updateStatus('ready', 'Ready for next call');
    });

    call.on('cancel', function() {
        log('Call cancelled');
        currentCall = null;
    });

    call.on('error', function(error) {
        log(`Call error: ${error.message}`, 'error');
        console.error('Call Error:', error);
    });
}

async function connectToAgentQueue(queueName) {
    // Connect agent directly to their queue where customers will be bridged
    const call = await device.connect({
        params: {
            To: `queue:${queueName}`,
            campaign_id: campaign ? campaign.id : '',
            agent_name: agentName || ''
        }
    });

    setupCallHandlers(call);
    log('Connected to agent queue - waiting for calls...', 'success');
    updateStatus('ready', 'Waiting for leads to connect');
}

// ============== UI Updates ==============

function isTerminalContactStatus(status) {
    return [
        'completed',
        'busy',
        'no-answer',
        'failed',
        'canceled',
        'ended',
        'voicemail'
    ].includes(status);
}

function markAnsweredIfApplicable(phone, status) {
    if (['queued', 'connected', 'in-progress', 'answered'].includes(status)) {
        answeredPhones.add(phone);
    }
}

function formatOutcome(phone, terminalStatus) {
    if (answeredPhones.has(phone)) return '✅ Answered';
    if (terminalStatus === 'busy') return '⛔ Busy / Rejected';
    if (terminalStatus === 'no-answer') return '⚪ No Answer';
    if (terminalStatus === 'failed') return '❌ Failed';
    if (terminalStatus === 'canceled') return '⚪ Canceled';
    if (terminalStatus === 'voicemail') return '📧 Voicemail';
    if (terminalStatus === 'ended') return '🏁 Ended';
    if (terminalStatus === 'completed') return '✓ Completed';
    return formatStatus(terminalStatus);
}

function renderCallHistory() {
    // Re-check DOM elements availability
    callHistoryContainer = document.getElementById('callHistoryContainer');
    callHistoryList = document.getElementById('callHistoryList');
    callHistoryCount = document.getElementById('callHistoryCount');

    if (!callHistoryContainer || !callHistoryList || !callHistoryCount) return;

    const entries = Object.values(callHistoryByPhone || {}).sort((a, b) => b.updatedAt - a.updatedAt);

    if (!entries.length) {
        callHistoryContainer.style.display = 'none';
        callHistoryCount.textContent = '0';
        callHistoryList.innerHTML = '';
        return;
    }

    callHistoryContainer.style.display = 'block';
    callHistoryCount.textContent = String(entries.length);

    callHistoryList.innerHTML = entries.map((e) => `
        <div class="contact-item ${e.status}" data-phone="${e.phone}">
            <span class="contact-number">${e.phone}</span>
            <span class="contact-status ${e.status}">${e.outcome}</span>
        </div>
    `).join('');
}

function renderContacts() {
    if (!campaign) return;

    // Re-check DOM elements availability (in case they were removed/recreated)
    contactListContainer = document.getElementById('contactListContainer');
    contactList = document.getElementById('contactList');
    contactCount = document.getElementById('contactCount');

    if (!contactListContainer || !contactList || !contactCount) return;

    const statusMap = campaign.contact_status || {};
    visibleContacts = (campaign.contacts || []).filter((phone) => {
        const status = statusMap[phone] || 'pending';
        return !isTerminalContactStatus(status);
    });

    contactListContainer.style.display = 'block';
    contactCount.textContent = visibleContacts.length;

    contactList.innerHTML = visibleContacts.map((phone) => {
        const status = statusMap[phone] || 'pending';
        return `
            <div class="contact-item ${status}" data-phone="${phone}">
                <span class="contact-number">${phone}</span>
                <span class="contact-status ${status}">${formatStatus(status)}</span>
            </div>
        `;
    }).join('');
}

function displayContacts(campaignData) {
    console.log('displayContacts:', {
        contacts: campaignData.contacts,
        is_recycling: campaignData.is_recycling
    });

    // Re-check DOM elements availability (in case they were removed/recreated)
    contactListContainer = document.getElementById('contactListContainer');
    contactList = document.getElementById('contactList');
    contactCount = document.getElementById('contactCount');

    if (!contactListContainer || !contactList || !contactCount) {
        console.log('ERROR: displayContacts - missing DOM elements');
        return;
    }

    try {
        const prevCampaignId = campaign ? campaign.id : null;

        // Keep global campaign state in sync, then render.
        campaign = campaignData;
        campaign.contacts = campaignData.contacts || [];
        campaign.contact_status = campaignData.contact_status || {};
        // Only reset outcomes/history when this is a NEW campaign.
        // (campaign_updated snapshots should NOT wipe previous outcomes.)
        if (!historyCampaignId || historyCampaignId !== campaign.id || (prevCampaignId && prevCampaignId !== campaign.id)) {
            callHistoryByPhone = {};
            answeredPhones = new Set();
            historyCampaignId = campaign.id || null;
        }
        renderContacts();
        renderCallHistory();

        // No "Next Batch" panel (agent has a fixed assigned pool)
    } catch (error) {
        console.error('Error in displayContacts:', error);
    }
}

// Next batch UI removed (agent has a fixed assigned pool)

function updateContactStatus(contactStatus) {
    if (!campaign) return;
    const prevStatus = campaign.contact_status || {};
    campaign.contact_status = contactStatus || {};
    
    let connectedCount = 0;
    let ringingCount = 0;
    let dialingCount = 0;
    let connectedPhone = null;
    
    (campaign.contacts || []).forEach((phone) => {
        const status = (contactStatus || {})[phone] || 'pending';
        markAnsweredIfApplicable(phone, status);

        if (isTerminalContactStatus(status)) {
            const prev = prevStatus[phone] || 'pending';
            // Record outcome when a call first reaches a terminal state (or if it changes)
            if (!isTerminalContactStatus(prev) || prev !== status) {
                callHistoryByPhone[phone] = {
                    phone,
                    status,
                    outcome: formatOutcome(phone, status),
                    updatedAt: Date.now()
                };
            }
        }
        if (status === 'in-progress' || status === 'connected') {
            connectedCount++;
            connectedPhone = phone;
            currentConnectedPhone = phone;
        }
        if (status === 'ringing') ringingCount++;
        if (status === 'dialing' || status === 'initiated' || status === 'queued') dialingCount++;
    });

    // Update the UI list; terminal statuses get removed from screen.
    renderContacts();
    renderCallHistory();
    
    if (connectedCount > 0 && currentConnectedPhone === connectedPhone) {
        updateStatus('connected', `Speaking with ${connectedPhone}`);
    } else if (connectedCount === 0 && currentConnectedPhone) {
        currentConnectedPhone = null;
        if (ringingCount > 0) {
            updateStatus('ready', `📞 ${ringingCount} lead(s) ringing...`);
        } else if (dialingCount > 0) {
            updateStatus('ready', `📱 Dialing ${dialingCount} lead(s)...`);
        } else {
            updateStatus('ready', 'Waiting for leads to connect...');
        }
    } else if (ringingCount > 0) {
        updateStatus('ready', `📞 ${ringingCount} lead(s) ringing...`);
    } else if (dialingCount > 0) {
        updateStatus('ready', `📱 Dialing ${dialingCount} lead(s)...`);
    }
}

function formatStatus(status) {
    const statusMap = {
        'pending': 'Pending',
        'dialing': 'Dialing...',
        'queued': 'Queued',
        'initiated': 'Calling...',
        'ringing': '📞 Ringing...',
        'connected': '🎯 Connected',
        'in-progress': '🟢 On Call',
        'answered': '🟢 On Call',
        'completed': '✓ Call Ended',
        'busy': '🔴 Busy',
        'no-answer': '⚪ No Answer',
        'failed': '❌ Failed',
        'canceled': '⚪ Cancelled',
        'voicemail': '📧 Voicemail',
        'ended': '🏁 Campaign Ended'
    };
    return statusMap[status] || status;
}

// ============== End Campaign ==============

window.endCampaign = async function() {
    log('Ending campaign...');
    if (endCampaignBtn) endCampaignBtn.disabled = true;
    
    if (agentName) {
        try {
            const resp = await fetch(`/api/agent/${encodeURIComponent(agentName)}/end`, { method: 'POST' });
            const data = await resp.json().catch(() => ({}));
            if (resp.ok && data.status === 'no_active_campaign') {
                log('No active campaign to end (already ended)', 'info');
            } else if (resp.ok) {
                log('Campaign ended', 'success');
            } else {
                log(`Failed to end campaign (${resp.status})`, 'error');
            }
        } catch (error) {
            console.error('Error ending campaign:', error);
            log(`Error ending campaign: ${error.message}`, 'error');
        }
    }
    
    if (currentCall) {
        currentCall.disconnect();
    }
    
    if (device) {
        device.unregister();
    }
    
    disconnectWebSocket();
    hideDispositionModal();
    
    campaign = null;
    callHistoryByPhone = {};
    answeredPhones = new Set();
    historyCampaignId = null;
    renderCallHistory();
    currentCall = null;
    device = null;
    isMuted = false;
    
    startCampaignBtn.disabled = false;
    startCampaignBtn.style.display = 'inline-block';
    endCampaignBtn.style.display = 'none';
    if (muteBtn) {
        muteBtn.style.display = 'none';
        muteBtn.classList.remove('muted');
        muteBtn.textContent = '🎤 Mute';
    }
    
    updateStatus('idle', 'Campaign ended. Ready to start a new one.');
    log('Campaign ended', 'success');
};

// ============== Initialize ==============

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing...');
    
    // Initialize DOM elements
    statusIndicator = document.getElementById('statusIndicator');
    statusText = document.getElementById('statusText');
    agentInfo = document.getElementById('agentInfo');
    agentNameDisplay = document.getElementById('agentNameDisplay');
    startCampaignBtn = document.getElementById('startCampaignBtn');
    endCampaignBtn = document.getElementById('endCampaignBtn');
    muteBtn = document.getElementById('muteBtn');
    contactListContainer = document.getElementById('contactListContainer');
    contactList = document.getElementById('contactList');
    contactCount = document.getElementById('contactCount');
    callHistoryContainer = document.getElementById('callHistoryContainer');
    callHistoryList = document.getElementById('callHistoryList');
    callHistoryCount = document.getElementById('callHistoryCount');
    logContainer = document.getElementById('logContainer');
    
    // Modals
    agentNameModal = document.getElementById('agentNameModal');
    agentNameInput = document.getElementById('agentNameInput');
    campaignSelect = document.getElementById('campaignSelect');
    dispositionModal = document.getElementById('dispositionModal');
    dispositionPhone = document.getElementById('dispositionPhone');
    dispositionSelect = document.getElementById('dispositionSelect');
    dispositionNotes = document.getElementById('dispositionNotes');
    
    // Load campaigns
    loadCampaigns();
    
    // Focus on agent name input
    if (agentNameInput) {
        agentNameInput.focus();
        agentNameInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                setAgentName();
            }
        });
    }
    
    log('Sales Dialer POC loaded');
    
    if (typeof Twilio !== 'undefined') {
        log('Twilio SDK loaded', 'success');
    } else {
        log('Twilio SDK not loaded!', 'error');
    }
});

// ============== Campaign Loading ==============

async function loadCampaigns() {
    if (!campaignSelect) return;
    
    try {
        const response = await fetch('/api/campaigns');
        if (response.ok) {
            const data = await response.json();
            campaignSelect.innerHTML = '<option value="">Select a campaign...</option>';
            
            if (data.campaigns && data.campaigns.length > 0) {
                data.campaigns.forEach(campaign => {
                    const option = document.createElement('option');
                    option.value = campaign.id;
                    option.textContent = campaign.name;
                    campaignSelect.appendChild(option);
                });
            } else {
                campaignSelect.innerHTML = '<option value="">No campaigns available</option>';
            }
        } else {
            campaignSelect.innerHTML = '<option value="">Error loading campaigns</option>';
        }
    } catch (error) {
        console.error('Error loading campaigns:', error);
        campaignSelect.innerHTML = '<option value="">Error loading campaigns</option>';
    }
}
