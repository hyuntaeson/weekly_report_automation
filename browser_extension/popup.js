/**
 * Popup script for the Chrome Extension
 * Handles toggle switch and status display
 */

const toggleButton = document.getElementById('toggleButton');
const statusText = document.getElementById('statusText');

/**
 * Update UI based on current status
 */
function updateUI(enabled) {
  if (enabled) {
    toggleButton.classList.add('active');
    statusText.textContent = '활동 추적 중';
    statusText.classList.remove('disabled');
    statusText.classList.add('enabled');
  } else {
    toggleButton.classList.remove('active');
    statusText.textContent = '활동 추적 중지됨';
    statusText.classList.remove('enabled');
    statusText.classList.add('disabled');
  }
}

/**
 * Load current status from storage
 */
function loadStatus() {
  chrome.runtime.sendMessage(
    { action: 'getStatus' },
    (response) => {
      if (response && typeof response.enabled !== 'undefined') {
        updateUI(response.enabled);
      }
    }
  );
}

/**
 * Handle toggle button click
 */
toggleButton.addEventListener('click', () => {
  // Get current status and toggle it
  chrome.runtime.sendMessage(
    { action: 'getStatus' },
    (response) => {
      const currentStatus = response.enabled !== false;
      const newStatus = !currentStatus;
      
      // Save new status
      chrome.runtime.sendMessage(
        { action: 'setStatus', enabled: newStatus },
        (response) => {
          if (response && response.success) {
            updateUI(newStatus);
          }
        }
      );
    }
  );
});

// Load status when popup opens
loadStatus();
