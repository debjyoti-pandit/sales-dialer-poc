// Sales Dialer POC - Main Application
// Using Twilio Voice SDK 2.x + WebSocket for real-time updates

let device = null;
let currentCall = null;
let campaign = null;
let websocket = null;
let isMuted = false;
let currentConnectedPhone = null;
let agentName = null;

// DOM Elements
let statusIndicator, statusText, agentInfo, agentNameDisplay, startCampaignBtn, endCampaignBtn, muteBtn;
let contactListContainer, contactList, contactCount, logContainer;
let dispositionModal, dispositionPhone, dispositionSelect, dispositionNotes;
let agentNameModal, agentNameInput;

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
    
    agentName = name;
    agentNameModal.style.display = 'none';
    agentNameDisplay.textContent = `Agent: ${agentName}`;
    log(`Agent name set: ${agentName}`, 'success');
    
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
    
    log('Dialing next batch...');
    
    try {
        const response = await fetch(`/api/agent/${encodeURIComponent(agentName)}/dial-next-batch`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.phones && data.phones.length > 0) {
                log(`Calling ${data.count} contacts...`, 'success');
            } else {
                log('No more contacts to dial', 'info');
                updateStatus('idle', 'All contacts have been called');
            }
        }
    } catch (error) {
        console.error('Error dialing next batch:', error);
        log('Error dialing next batch', 'error');
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
            setTimeout(() => dialNextBatch(), 1000);
            break;
            
        case 'campaign_ended':
            log('Campaign ended by server');
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
        const campaignResponse = await fetch(`/api/campaign/start?agent_name=${encodeURIComponent(agentName)}`, {
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
            log(`Dialing ${campaign.contacts.length} contacts...`, 'success');
            displayContacts(campaign);
        } else {
            log('No contacts available to dial', 'info');
        }

        // Initialize Twilio Device
        await initializeDevice(token);

        // Agent connects to queue
        log('Connecting to queue...');
        await connectToQueue(agentName);

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

    device.on('incoming', function(call) {
        log('Incoming call from queue...');
        setupCallHandlers(call);
        call.accept();
    });

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
        updateStatus('on-call', 'On call');
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

async function connectToQueue(agentName) {
    // Connect to agent's queue - Twilio will call the device when a call is dequeued
    // The device will receive an incoming call which we handle in setupDeviceHandlers
    log('Ready to receive calls from queue', 'success');
    updateStatus('ready', 'Waiting for calls from queue...');
}

// ============== UI Updates ==============

function displayContacts(campaignData) {
    if (!contactListContainer || !contactList || !contactCount) return;
    
    contactListContainer.style.display = 'block';
    contactCount.textContent = campaignData.contacts.length;
    
    contactList.innerHTML = campaignData.contacts.map((contact, index) => `
        <div class="contact-item" id="contact-${index}" data-phone="${contact}">
            <span class="contact-number">${contact}</span>
            <span class="contact-status pending" id="status-${index}">Pending</span>
        </div>
    `).join('');
}

function updateContactStatus(contactStatus) {
    if (!campaign) return;
    
    let connectedCount = 0;
    let ringingCount = 0;
    let dialingCount = 0;
    let connectedPhone = null;
    
    campaign.contacts.forEach((phone, index) => {
        const status = contactStatus[phone] || 'pending';
        const itemEl = document.getElementById(`contact-${index}`);
        const statusEl = document.getElementById(`status-${index}`);
        
        if (itemEl && statusEl) {
            itemEl.className = `contact-item ${status}`;
            statusEl.className = `contact-status ${status}`;
            statusEl.textContent = formatStatus(status);
        }
        
        if (status === 'in-progress') {
            connectedCount++;
            connectedPhone = phone;
            currentConnectedPhone = phone;
        }
        if (status === 'ringing') ringingCount++;
        if (status === 'dialing' || status === 'initiated' || status === 'queued') dialingCount++;
    });
    
    if (connectedCount > 0 && currentConnectedPhone === connectedPhone) {
        updateStatus('connected', `🎉 Speaking with ${connectedPhone}`);
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
        'in-progress': '🟢 On Call',
        'answered': '🟢 On Call',
        'completed': '✓ Call Ended',
        'busy': '🔴 Busy',
        'no-answer': '⚪ No Answer',
        'failed': '❌ Failed',
        'canceled': '⚪ Cancelled',
        'voicemail': '📧 Voicemail'
    };
    return statusMap[status] || status;
}

// ============== End Campaign ==============

window.endCampaign = async function() {
    log('Ending campaign...');
    
    if (agentName) {
        try {
            await fetch(`/api/agent/${encodeURIComponent(agentName)}/end`, { method: 'POST' });
            log('Campaign ended', 'success');
        } catch (error) {
            console.error('Error ending campaign:', error);
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
    logContainer = document.getElementById('logContainer');
    
    // Modals
    agentNameModal = document.getElementById('agentNameModal');
    agentNameInput = document.getElementById('agentNameInput');
    dispositionModal = document.getElementById('dispositionModal');
    dispositionPhone = document.getElementById('dispositionPhone');
    dispositionSelect = document.getElementById('dispositionSelect');
    dispositionNotes = document.getElementById('dispositionNotes');
    
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
