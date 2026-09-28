/**
 * Background Service Worker for Chrome Extension
 * Monitors page visits and sends them to local activity server
 */

// Server configuration
const SERVER_URL = 'http://localhost:5757/activity';
const FALLBACK_SERVER_URL = 'http://127.0.0.1:5757/activity';

// Sensitive URL patterns to exclude
const SENSITIVE_PATTERNS = [
  'chrome://',
  'about:',
  'file://',
  'edge://',
  'accounts.google.com',
  'login.',
  'signin',
  'password',
  '.bank',
  'banking',
  'credit-card',
  'paypal.com',
  'github.com/login',
  'github.com/session',
  'facebook.com/login',
  'twitter.com/login',
  'microsoft.com/oauth',
  'oauth',
  'auth'
];

/**
 * Check if URL should be tracked
 */
function shouldTrackUrl(url) {
  if (!url) return false;
  
  // Check against sensitive patterns
  const lowerUrl = url.toLowerCase();
  for (const pattern of SENSITIVE_PATTERNS) {
    if (lowerUrl.includes(pattern.toLowerCase())) {
      return false;
    }
  }
  
  return true;
}

/**
 * Send activity to server
 */
async function sendActivity(url, title) {
  if (!shouldTrackUrl(url)) {
    console.warn(`[ActivityTracker] Skipped sensitive URL: ${url}`);
    return;
  }
  
  const activity = {
    url: url,
    title: title || 'No title',
    timestamp: new Date().toISOString()
  };
  
  try {
    // Try primary server first
    const response = await fetch(SERVER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(activity)
    });
    
    if (response.ok) {
      console.log(`[ActivityTracker] Sent: ${url}`);
    } else {
      console.warn(`[ActivityTracker] Server returned ${response.status}`);
    }
  } catch (error) {
    // Try fallback server
    try {
      const response = await fetch(FALLBACK_SERVER_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(activity)
      });
      
      if (response.ok) {
        console.log(`[ActivityTracker] Sent via fallback: ${url}`);
      }
    } catch (fallbackError) {
      // Server not running - silently ignore
      console.warn(`[ActivityTracker] Server unavailable. Make sure to run: python browser_activity_server.py`);
    }
  }
}

/**
 * Initialize extension - check if tracking is enabled
 */
chrome.runtime.onInstalled.addListener(() => {
  // Set default settings
  chrome.storage.local.get(['enabled'], (result) => {
    if (result.enabled === undefined) {
      chrome.storage.local.set({ enabled: true });
    }
  });
});

/**
 * Listen for tab updates
 */
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // Only process when page loading is complete
  if (changeInfo.status !== 'complete') {
    return;
  }
  
  // Check if tracking is enabled
  chrome.storage.local.get(['enabled'], (result) => {
    if (result.enabled === false) {
      return;
    }
    
    // Send activity
    if (tab.url && tab.title) {
      sendActivity(tab.url, tab.title);
    }
  });
});

/**
 * Handle messages from popup
 */
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getStatus') {
    chrome.storage.local.get(['enabled'], (result) => {
      sendResponse({ enabled: result.enabled !== false });
    });
  } else if (request.action === 'setStatus') {
    chrome.storage.local.set({ enabled: request.enabled }, () => {
      sendResponse({ success: true });
    });
  }
});

console.log('[ActivityTracker] Background service worker initialized');
