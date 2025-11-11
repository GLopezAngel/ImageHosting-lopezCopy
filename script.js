/*
 * ImageHost Frontend Script
 * Connects the HTML UI to the Flask backend and S3.
 */

const API_KEY_STORAGE = 'imagehost_api_key';
let filesToUpload = [];

// Helper to make API calls
async function apiFetch(endpoint, options = {}) {
  const headers = {
    'X-API-Key': localStorage.getItem(API_KEY_STORAGE) || '',
  };

  const isFormData = options.body instanceof FormData;

  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }

  options.headers = { ...headers, ...options.headers };

  if (!isFormData && options.body) {
    options.body = JSON.stringify(options.body);
  }

  const response = await fetch(endpoint, options);
  
  if (!response.ok) {
    let errorMessage;
    try {
      const err = await response.json();
      errorMessage = err.error?.message || 'API request failed';
    } catch (e) {
      errorMessage = `Server error: ${response.status} ${response.statusText}`;
    }
    throw new Error(errorMessage);
  }
  
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

// 1. Get or create a dev API key on load
async function initApiKey() {
  let key = localStorage.getItem(API_KEY_STORAGE);
  if (key) {
    console.log('Using existing API key');
    return key;
  }

  console.log('No API key found, issuing a new one...');
  try {
    const data = await apiFetch('/api/v1/dev/issue-key', {
      method: 'POST',
      body: {}, // Send an empty JSON object
    });
    
    if (!data.api_key) {
      throw new Error("Server didn't return an API key.");
    }
    
    localStorage.setItem(API_KEY_STORAGE, data.api_key);
    console.log('New dev key issued and stored');
    return data.api_key;
  } catch (error) {
    console.error('Failed to issue dev key:', error);
  }
}

// 2. Handle file selection (drag & drop, file input)
function setupFileHandling(dropzone, fileInput, uploadBtn) {
  let fileList = [];

  function updateFileList(newFiles) {
    fileList = [...newFiles];
    if (fileList.length > 0) {
      dropzone.querySelector('p').textContent = `${fileList.length} file(s) selected`;
      uploadBtn.disabled = false;
    } else {
      dropzone.querySelector('p').textContent = 'Drag & drop images here';
      uploadBtn.disabled = true;
    }
    filesToUpload = fileList;
  }

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    updateFileList(e.dataTransfer.files);
  });

  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => updateFileList(fileInput.files));
}

// 3. Handle the S3 upload process
async function handleUpload(uploadBtn, progressBarEl, resultsEl, linksListEl) {
  uploadBtn.disabled = true;
  progressBarEl.parentElement.classList.add('active');
  resultsEl.hidden = true;
  linksListEl.innerHTML = '';

  const totalFiles = filesToUpload.length;
  let filesUploaded = 0;

  for (const file of filesToUpload) {
    try {
      // Step A: Ask our backend for a presigned S3 URL
      const { presigned_url, iid, key } = await apiFetch('/api/v1/upload/request', {
        method: 'POST',
        body: {
          filename: file.name,
          mime_type: file.type,
        },
      });

      // Step B: Upload the file directly to S3
      const s3Response = await fetch(presigned_url, {
        method: 'PUT',
        body: file,
        headers: {
          'Content-Type': file.type,
          'x-amz-acl': 'public-read' // <-- THIS HEADER IS NOW ADDED BACK
        },
      });

      if (!s3Response.ok) {
        throw new Error('S3 upload failed'); // This will be caught
      }

      // Step C: Tell our backend the upload is complete
      const { url } = await apiFetch('/api/v1/upload/complete', {
        method: 'POST',
        body: {
          iid: iid,
          key: key,
          filename: file.name,
          mime_type: file.type,
        },
      });

      // Update UI
      addLinkToResults(url, linksListEl);
      filesUploaded++;
      progressBarEl.style.width = `${(filesUploaded / totalFiles) * 100}%`;

    } catch (error) {
      // This is where your console logs "Failed to upload file..."
      console.error('Failed to upload file:', file.name, error);
    }
  } // The loop finishes, and...

  // Done
  uploadBtn.disabled = false;
  resultsEl.hidden = false;
  filesToUpload = [];
  
  // ...this misleadingly logs, even if a file failed.
  console.log('All uploads complete'); 
  
  // Refresh the gallery after uploads are done
  setTimeout(() => {
    document.getElementById('refresh-gallery').click();
  }, 200);
}

// 4. Handle refreshing the gallery
async function refreshGallery(gridEl) {
  gridEl.innerHTML = '<p class="grid-item-placeholder">Loading...</p>';
  try {
    const { items } = await apiFetch('/api/v1/me/images');
    gridEl.innerHTML = '';

    if (!items || items.length === 0) {
      gridEl.innerHTML = '<p class="grid-item-placeholder">No images uploaded yet.</p>';
      return;
    }

    items.forEach((item) => {
      const el = document.createElement('div');
      el.className = 'grid-item';
      el.innerHTML = `<img src="${item.url}" alt="${item.filename}" loading="lazy">`;
      
      el.addEventListener('click', () => showImageModal(item));
      
      gridEl.appendChild(el);
    });
  } catch (error) {
    console.error('Failed to refresh gallery:', error);
    gridEl.innerHTML = '<p class="grid-item-placeholder" style="color: red;">Failed to load images.</p>';
  }
}

// 5. UI Helpers
function addLinkToResults(url, listEl) {
  const item = document.createElement('li');
  item.className = 'link-item';
  item.innerHTML = `
    <input class="link-url" type="text" value="${url}" readonly>
    <button class="button copy-btn">Copy</button>
  `;
  item.querySelector('.copy-btn').addEventListener('click', (e) => {
    e.target.textContent = 'Copied!';
    navigator.clipboard.writeText(url);
    setTimeout(() => {
      e.target.textContent = 'Copy';
    }, 2000);
  });
  listEl.prepend(item);
}

// 6. Function to show the image modal
function showImageModal(item) {
  const modal = document.getElementById('image-modal');
  const modalImg = document.getElementById('modal-img');
  const modalLinkInput = document.getElementById('modal-link-input');

  modalImg.src = item.url;
  modalImg.alt = item.filename;
  modalLinkInput.value = item.url;
  
  modal.style.display = 'flex';
}

// --- Main execution ---
document.addEventListener('DOMContentLoaded', () => {
  // Get all DOM elements
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const uploadBtn = document.getElementById('upload-btn');
  const progressBar = document.getElementById('progress-bar');
  const uploadResults = document.getElementById('upload-results');
  const linksList = document.getElementById('links-list');
  const galleryGrid = document.getElementById('gallery-grid');
  const refreshBtn = document.getElementById('refresh-gallery');
  const modal = document.getElementById('image-modal');
  const modalCloseBtn = document.getElementById('modal-close-btn');
  const modalCopyBtn = document.getElementById('modal-copy-btn');
  const modalLinkInput = document.getElementById('modal-link-input');

  if (!dropzone) {
    console.error('Fatal: UI elements not found!');
    return;
  }

  // Set up all event listeners
  setupFileHandling(dropzone, fileInput, uploadBtn);
  uploadBtn.addEventListener('click', () =>
    handleUpload(uploadBtn, progressBar, uploadResults, linksList)
  );
  refreshBtn.addEventListener('click', () => refreshGallery(galleryGrid));

  // Add Modal event listeners
  function closeModal() {
    modal.style.display = 'none';
  }

  modalCloseBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeModal();
    }
  });

  modalCopyBtn.addEventListener('click', (e) => {
    e.target.textContent = 'Copied!';
    navigator.clipboard.writeText(modalLinkInput.value);
    setTimeout(() => {
      e.target.textContent = 'Copy';
    }, 2000);
  });

  // Init API key and load initial gallery
  initApiKey().then(() => {
    refreshGallery(galleryGrid);
  });
});