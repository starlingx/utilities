function ConfirmDelete(elem) {
    localStorage.setItem('deleteId', $(elem).attr('data-id'));
    $('#deleteModal').modal();
}

function Delete() {
    $.ajax({
        url: '/delete_file',
        data: {
            id: localStorage.getItem('deleteId')
        },
        type: 'POST',
        success: function(res) {
            $('#deleteModal').modal('hide');
            location.reload();
        },
        error: function(error) {
            console.log(error);
        }
    });
}

// Get a reference to the progress bar, wrapper & status label
var progress_wrapper = document.getElementById("progress_wrapper");

// Get a reference to the 3 buttons
var upload_btn = document.getElementById("upload_btn");
var loading_btn = document.getElementById("loading_btn");
var cancel_btn = document.getElementById("cancel_btn");

// Get a reference to the alert wrapper
var alert_wrapper = document.getElementById("alert_wrapper");

// Get a reference to the file input element & input label
var input = document.getElementById("file_input");
var launchpad_input = document.getElementById("launchpad_input");
var file_input_label = document.getElementById("file_input_label");

var search_input_label = document.getElementById("search_input_label");
var launchpad_info = document.getElementById("launchpad_info");

var upload_count = 0;

function search() {
    search_input = search_input_label.value;
    location.search = "?search="+search_input;
}

// Function to show alerts
function show_alert(message, alert) {

  alert_wrapper.innerHTML = alert_wrapper.innerHTML + `
    <div id="alert" class="alert alert-${alert} alert-dismissible fade show" role="alert">
      <span>${message}</span>
      <button type="button" class="close" data-dismiss="alert" aria-label="Close">
        <span aria-hidden="true">&times;</span>
      </button>
    </div>
  `

}

function revert() {
    var tbody = $('table tbody');
    tbody.html($('tr',tbody).get().reverse());
    if (document.getElementById("table_order").classList.contains("fa-caret-square-o-down")) {
        document.getElementById("table_order").classList.remove("fa-caret-square-o-down");
        document.getElementById("table_order").classList.add("fa-caret-square-o-up");
    } else {
        document.getElementById("table_order").classList.remove("fa-caret-square-o-up");
        document.getElementById("table_order").classList.add("fa-caret-square-o-down");
    }
}

function upload() {

  upload_count = 0

  // Reject if the file input is empty & throw alert
  if (!input.value) {

    show_alert("No file selected", "warning")

    return;

  }

  var request = new XMLHttpRequest();
  var launchpad_id = launchpad_input.value;

  request.open("get", "http://128.224.141.2:5000/check_launchpad/"+launchpad_id);
  request.send();

  // Clear any existing alerts
  alert_wrapper.innerHTML = "";

  request.addEventListener("load", function (e) {

    if (request.status == 200) {

      // Hide the upload button
      upload_btn.classList.add("d-none");

      // Show the loading button
      loading_btn.classList.remove("d-none");

      // Show the cancel button
      cancel_btn.classList.remove("d-none");

      // Show the progress bar
      progress_wrapper.classList.remove("d-none");

      // Show the progress bar
      launchpad_info.classList.remove("d-none");

      launchpad_info.innerHTML = 'Launchpad title: '+request.response;

      // Disable the input during upload
      input.disabled = true;
      launchpad_input.disabled = true;

      progress_wrapper.innerHTML = ""

      for (var i = 0; i < input.files.length; i++) {
        progress_wrapper.innerHTML = progress_wrapper.innerHTML + `
          <div id="progress_wrapper_${i}">
            <label id="progress_status_${i}">Initializing upload...</label>
            <button type="button" id="cancel_btn_${i}" class="btn btn-secondary btn-sm">Cancel</button>
            <button type="button" id="ignore_btn_${i}" class="btn btn-secondary btn-sm d-none">Cancel</button>
            <button type="button" id="overwrite_btn_${i}" class="btn btn-danger btn-sm d-none">Overwrite</button>
            <button type="button" id="rename_btn_${i}" class="btn btn-primary btn-sm d-none">Rename</button>
            <div class="progress mb-3">
              <div id="progress_${i}" class="progress-bar" role="progressbar" aria-valuenow="25" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
          </div>`
      }

      for (var i = 0; i < input.files.length; i++) {
        upload_single_file(input.files[i], i);
      }

    }
    else {

      // Reset the input placeholder
      file_input_label.innerText = "Select file or drop it here to upload";
      launchpad_input.innerText = "";

      show_alert(`${request.response}`, "danger");

    }

  });

//  reset();
}

// Function to upload single file
function upload_single_file(file, i) {

  var progress_wrapper_single = document.getElementById(`progress_wrapper_${i}`);
  var progress = document.getElementById(`progress_${i}`);
  var progress_status = document.getElementById(`progress_status_${i}`);

  var cancel_btn_single = document.getElementById(`cancel_btn_${i}`);
  var ignore_btn_single = document.getElementById(`ignore_btn_${i}`);
  var overwrite_btn_single = document.getElementById(`overwrite_btn_${i}`);
  var rename_btn_single = document.getElementById(`rename_btn_${i}`);

  var url = "http://128.224.141.2:5000/upload/"

  // Create a new FormData instance
  var data = new FormData();

  // Create a XMLHTTPRequest instance
  var request = new XMLHttpRequest();
  var request_file_check = new XMLHttpRequest();

  // Set the response type
  request.responseType = "json";

  // Get a reference to the files
//  var file = input.files[0];
  // Get a reference to the launchpad id
  var launchpad_id = launchpad_input.value;

//  // Get a reference to the filename
//  var filename = file.name;

  // Get a reference to the filesize & set a cookie
//  var filesize = file.size;
//  document.cookie = `filesize=${filesize}`;

  // Append the file to the FormData instance
//  data.append("file", file);

  request_file_check.open("get", '/file_exists/?launchpad_id='+launchpad_id+'&file_name='+file.name);
  request_file_check.send();

  request_file_check.addEventListener("load", function (e) {
    if (request_file_check.responseText == '0'){
      // Open and send the request
      request.open("post", url+"?launchpad_id="+launchpad_id);
      data = new FormData();
      data.append("file", file);
      request.send(data);
    } else if (request_file_check.responseText == '1'){
      progress_status.innerText = `File already exists: ${file.name}`;
      progress_status.style.color = 'red';
      cancel_btn_single.classList.add("d-none");
      ignore_btn_single.classList.remove("d-none");
      overwrite_btn_single.classList.remove("d-none");
      rename_btn_single.classList.remove("d-none");
    } else {
      show_alert('Error: you did not supply a valid file in your request', "warning");
      upload_count++;

      if (upload_count == input.files.length){
        reset();
      }
    }
  });

  ignore_btn_single.addEventListener("click", function () {

    progress_status.style.color = 'black';

    cancel_btn_single.classList.remove("d-none");
    ignore_btn_single.classList.add("d-none");
    overwrite_btn_single.classList.add("d-none");
    rename_btn_single.classList.add("d-none");

    show_alert(`Upload cancelled: ${file.name}`, "primary");

    progress_wrapper_single.classList.add("d-none");

    upload_count++;

    if (upload_count == input.files.length){
      reset();
    }

  })

  overwrite_btn_single.addEventListener("click", function () {

    progress_status.style.color = 'black';

    cancel_btn_single.classList.remove("d-none");
    ignore_btn_single.classList.add("d-none");
    overwrite_btn_single.classList.add("d-none");
    rename_btn_single.classList.add("d-none");

    request.open("post", url+"?launchpad_id="+launchpad_id+'&conflict=0');
    data = new FormData();
    data.append("file", file);
    request.send(data);

  })

  rename_btn_single.addEventListener("click", function () {

    progress_status.style.color = 'black';

    cancel_btn_single.classList.remove("d-none");
    ignore_btn_single.classList.add("d-none");
    overwrite_btn_single.classList.add("d-none");
    rename_btn_single.classList.add("d-none");

    request.open("post", url+"?launchpad_id="+launchpad_id+'&conflict=1');
    data = new FormData();
    data.append("file", file);
    request.send(data);

  })

  // request progress handler
  request.upload.addEventListener("progress", function (e) {

    // Get the loaded amount and total filesize (bytes)
    var loaded = e.loaded;
    var total = e.total;

    // Calculate percent uploaded
    var percent_complete = (loaded / total) * 100;

    // Update the progress text and progress bar
    progress.setAttribute("style", `width: ${Math.floor(percent_complete)}%`);
    progress_status.innerText = `${Math.floor(percent_complete)}% uploaded: ${file.name}`;

    if (loaded == total) {
      progress_status.innerText = `Saving file: ${file.name}`;
    }

  })

  // request load handler (transfer complete)
  request.addEventListener("load", function (e) {

    if (request.status == 200) {

      show_alert(`${request.response.message}`, "success");

    }
    else {

      show_alert(`${request.response.message}`, "danger");

    }

    progress_wrapper_single.classList.add("d-none");

    upload_count++;

    if (upload_count == input.files.length){
      reset();
    }

  });

  // request error handler
  request.addEventListener("error", function (e) {

    show_alert(`Error uploading file: ${file.name}`, "warning");

    progress_wrapper_single.classList.add("d-none");

    upload_count++;

    if (upload_count == input.files.length){
      reset();
    }

  });

  // request abort handler
  request.addEventListener("abort", function (e) {

    show_alert(`Upload cancelled: ${file.name}`, "primary");

    progress_wrapper_single.classList.add("d-none");

    upload_count++;

    if (upload_count == input.files.length){
      reset();
    }

  });

  cancel_btn.addEventListener("click", function () {

    request.abort();

  })

  cancel_btn_single.addEventListener("click", function () {

    request.abort();

  })

}

// Function to update the input placeholder
function input_filename() {
//    file_input_label.innerText = typeof input.files;
//    var all_files = input.files.values().reduce(function (accumulator, file) {
//      return accumulator + file.name;
//    }, 0);

    var all_files = input.files[0].name;

    for (var i = 1; i < input.files.length; i++){
        all_files = all_files + ', ' + input.files[i].name
    }
    file_input_label.innerText = all_files;

//    file_input_label.innerText = input.files[0].name;
//    file_input_label.innerText = input.files.toString();

}

// Function to reset the page
function reset() {

  // Clear the input
  input.value = null;

  // Hide the cancel button
  cancel_btn.classList.add("d-none");

  // Reset the input element
  input.disabled = false;
  launchpad_input.disabled = false;

  // Show the upload button
  upload_btn.classList.remove("d-none");

  // Hide the loading button
  loading_btn.classList.add("d-none");

  // Hide the progress bar
  progress_wrapper.classList.add("d-none");

  // Reset the input placeholder
  file_input_label.innerText = "Select file or drop it here to upload";
  launchpad_input.innerText = "";

  // Show the progress bar
  launchpad_info.classList.add("d-none");

  launchpad_info.innerHTML = "";

}