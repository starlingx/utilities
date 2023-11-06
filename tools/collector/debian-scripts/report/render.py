########################################################################
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the Render function
# The Rendering tool visualizes the collect bundle and generates index.html file
#
########################################################################

from datetime import datetime
import os


def extract_section(log_contents, start_phrase):
    """extract the correlated or plugin content of the summary

    Parameters:
    log_contents (string): content of the log
    start_phrase (string): the name of the section extracted
    """
    start = log_contents.find(start_phrase)
    if start == -1:
        return ""
    end = log_contents.find("\n\n", start)
    if end == -1:
        end = len(log_contents)
    return log_contents[start:end].strip()


def remove_timestamp(text):
    """remove timestamp of summary message

    Parameters:
    text (string): the summary message
    """
    lines = text.split('\n')
    temp = []
    for line in lines:
        split_string = line.split(' ', 1)
        # check if the first part is time format, then remove if it is
        if split_string[0] and datetime.fromisoformat(split_string[0]):
            temp.append(split_string[1])
        else:
            temp.append(line)
    final_text = '\n'.join(temp)
    return final_text


def remove_emptyinfo(text):
    """ remove 'INFO' text of summary message

    Parameters:
    text (string): the summary message
    """
    lines = text.split('\n')
    temp = []
    for line in lines:
        if line.strip() != 'INFO:':
            temp.append(line)
    final_text = '\n'.join(temp)
    return final_text


def process_section(section, title):
    """return text with timestamp and INFO: removed

    Parameters:
    section (string): the message of the correlated/plugins section
    title (string): correlated/plugin results
    """
    section = section[len(title):]
    section = remove_timestamp(section)
    section = remove_emptyinfo(section)
    return section


def classify_node(data):
    """classify node type in system_info summary

    Parameters:
    data (string): the summary of system_info
    """
    node_type = ''
    for item in data:
        if 'Node Type' in item:
            node_type = item.split(':')[-1].strip().lower()
    return node_type


def controller_sort(x):
    """sort the controller, place the controller-0 first

    Parameters:
    x (list): list of controller info
    """
    return x[0] != 'controller-0'


def html_css():
    """static css code of the rendering tool

    iframe, textarea: the content panel showing information
    #show-worker: the show more worker button
    .container-menu: the overall layout of the page
    .menu: the sidebar menu of the page
    #correlated-results-toggle, #plugin-results-toggle: +/- button for results menu
    """
    html_content_css = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Report Analysis</title>
        <style>
            html, body {{
                overflow-x: hidden;
            }}

            iframe, textarea {{
                height: 70vh;
                width: 70vw;
                resize: none;
            }}

            #content-maxheight {{
                max-height: 70vh;
                overflow-y: scroll;
            }}

            .container-menu {{
                display: grid;
                grid-template-columns: 25% 75%;
                grid-gap: 10px;
                background-color: #f0f0f0;
            }}

            .menu {{
                padding: 20px;
                background-color: #f0f0f0;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                overflow-y: auto;
                max-height: 80vh;
            }}

            .menu ul, .menu li {{
                list-style-type: none;
                padding: 0;
                margin-bottom: 5px;
            }}

            .menu a,
            .menuItem,
            #plugin-results-submenu a,
            #correlated-results-submenu a,
            #storage-info-submenu a,
            #worker-info-submenu a {{
                text-decoration: none;
                color: #00ada4;
                font-weight: bold;
                display: block;
                padding: 6px 10px;
            }}

            .menuTitle {{
                color: #00857e !important;
            }}

            .menuItem {{
                cursor: pointer;
                display: flex;
            }}

            .menuItem .icon {{
                margin-right: 5px;
            }}

            .icon {{
                display: inline-block;
            }}

            .menu a:hover, .menuItem:hover {{
                background-color: #c3e3e2;
                border-radius: 3px;
            }}

            .content {{
                padding: 10px;
                font-family: monospace;
                margin-top: 10px;
            }}

            .content-item, .content-itemtwo {{
                display: none;
            }}

            .hidden {{
                display: none;
            }}

            #show-worker {{
                background-color: #00857e;
                color: white;
                border: none;
                padding: 10px 20px;
                cursor: pointer;
            }}

            #show-worker:disabled {{
                background-color: #ccc;
                cursor: not-allowed;
            }}

            #correlated-results-toggle, #plugin-results-toggle {{
                color: #2F4F4F;
            }}

        </style>
    </head>
    """
    return html_content_css


def html_script():
    """static script code

    Functions:
    toggleContent: show content in System Info section
    toggleSub: show/hide submenus in correlated/plugin results
    toggleMenu: show the correlated/plugin summary
    showContentStorage: display content of selected storage item
    showContentWorker: display content of selected worker item
    showContentTwo: display content of result section
    """
    html_content_script = """
    <script>

    function toggleSub(event, submenuId, toggleButtonId) {{
        event.preventDefault();

        const submenu = document.getElementById(submenuId);
        const toggleButton = document.getElementById(toggleButtonId);

        if (submenu.style.display === "none") {{
            submenu.style.display = "block";
            toggleButton.textContent = "- ";
        }} else {{
            submenu.style.display = "none";
            toggleButton.textContent = "+ ";
        }}
    }}

    function toggleMenu(event, submenuId) {{
        if (submenuId === 'correlated-results-submenu') {{
            showContentTwo(event, 'content-item-correlated_results');
        }}

        if (submenuId === 'plugin-results-submenu') {{
            showContentTwo(event, 'content-item-plugin_results');
        }}
    }}

    function showContentStorage(event, contentId) {{
        event.preventDefault();

        const submenu = document.getElementById('storage-info-submenu');
        const element = document.getElementById('storageicon');
        var subicon = submenu.getElementsByClassName('icon');

        if (submenu.style.display === 'block') {{
            submenu.style.display = 'none';
            element.textContent = '+';
            for (var i = 0; i < subicon.length; i++) {{
                    subicon[i].textContent = '+';
            }}
            hideAllStorageId();
        }} else {{
            submenu.style.display = 'block';
            element.textContent = '-';
        }}
    }}

    function showContentWorker(event, contentId) {{
        event.preventDefault();

        const submenu = document.getElementById('worker-info-submenu');
        const element = document.getElementById('workericon');
        var subicon = submenu.getElementsByClassName('icon');

        if (submenu.style.display === 'block') {{
            submenu.style.display = 'none';
            element.textContent = '+';
            for (var i = 0; i < subicon.length; i++) {{
                    subicon[i].textContent = '+';
            }}
            if (document.getElementById("show-worker")) {{
                document.getElementById("show-worker").disabled = true;
            }}
            hideAllWorkerId();
        }} else {{
            submenu.style.display = 'block';
            element.textContent = '-';
            if (document.getElementById("show-worker")) {{
                document.getElementById("show-worker").disabled = false;
            }}
        }}
    }}

    function showContentTwo(event, contentId) {{
        event.preventDefault();

        const contentItems = document.querySelectorAll('.content-itemtwo');
        contentItems.forEach(item => {{
            item.style.display = 'none';
        }});

        const selectedContent = document.getElementById(contentId);
        if (selectedContent) {{
            selectedContent.style.display = 'block';
        }}
    }}

    function toggleContent(option, menuItem) {{
        const contentDiv = document.getElementById(option);
        const icon = menuItem.querySelector('.icon');

        if (contentDiv.style.display === 'none') {{
            contentDiv.style.display = 'block';
            icon.textContent = '-';
        }} else {{
            contentDiv.style.display = 'none';
            icon.textContent = '+';
        }}
    }}

    function hideAllStorageId() {{
        var outerDiv = document.getElementById('content-maxheight');
        var innerDivs = outerDiv.getElementsByTagName('div');
        var ids = [];

        for (var i = 0; i < innerDivs.length; i++) {{
            if (innerDivs[i].id) {{
                ids.push(innerDivs[i].id);
            }}
        }}

        for (var i = 0; i < ids.length; i++) {{
            if (ids[i].includes("storage")) {{
                document.getElementById(ids[i]).style.display = 'none';
            }}
        }}
    }}

    function hideAllWorkerId() {{
        var outerDiv = document.getElementById('content-maxheight');
        var innerDivs = outerDiv.getElementsByTagName('div');
        var ids = [];

        for (var i = 0; i < innerDivs.length; i++) {{
            if (innerDivs[i].id) {{
                ids.push(innerDivs[i].id);
            }}
        }}

        for (var i = 0; i < ids.length; i++) {{
            if (!ids[i].includes("controller")
            && !ids[i].includes("storage")) {{
                document.getElementById(ids[i]).style.display = 'none';
            }}
        }}

        var hiddenItems = document.querySelectorAll(".menuItem.nothidden");
        for (var i = 0; i < hiddenItems.length; i++) {{
            hiddenItems[i].classList.remove("nothidden");
            hiddenItems[i].classList.add("hidden");
        }}
    }}

    function showMoreWorker() {{
        var visibleItemCount = 5;
        var hiddenItems = document.querySelectorAll(".menuItem.hidden");
        for (var i = 0; i < hiddenItems.length; i++) {{
            if (i < visibleItemCount) {{
                hiddenItems[i].classList.remove("hidden");
                hiddenItems[i].classList.add("nothidden");
            }}
        }}

        if (hiddenItems.length <= visibleItemCount) {{
            var button = document.getElementById("show-worker");
            button.disabled = true;
        }}
    }}

    </script>
    </html>
    """
    return html_content_script


def html_info(sys_section):
    """system info part generation
    reads from plugin/system_info and show by different types
    order: controller, storage(if there exists), worker(if there exists)

    Parameters:
    sys_section (string): the summary of system_info
    """
    controller_section = []
    storage_section = []
    worker_section = []

    for i in sys_section:
        section_lines = i.strip().split("\n")
        section_type = classify_node(section_lines)

        if "controller" == section_type:
            controller_section.append(section_lines)

        if "storage" == section_type:
            storage_section.append(section_lines)

        if "worker" == section_type:
            worker_section.append(section_lines)

    controller_section = sorted(controller_section, key=controller_sort)

    controller_zero = controller_section.pop(0)

    sections = {
        "controller": controller_section,
        "storage": storage_section,
        "worker": worker_section
    }

    html_content_one = ""

    html_content_one += """
    <body>
    <div class="container-menu">
        <div class="menu">
        <ul>
        <a href="#" class="menuTitle" onclick="location.reload()">System Information</a>
    """

    html_content_one += "<li>"
    html_content_one += """<div class="menuItem" onclick="toggleContent('controller-0', this)">"""
    html_content_one += """<div class="icon">-</div> controller-0</div>"""
    for i in range(len(controller_section)):
        controlname = controller_section[i][0]
        html_content_one += f'<div class="menuItem" onclick="toggleContent(\'{controlname}\', this)">'
        html_content_one += f'<div class="icon">+</div> {controlname}</div>'
    html_content_one += "</li><hr>"

    if storage_section:
        html_content_one += """<li><a href="#" onclick="showContentStorage(event, 'storage')" style="color: #00857e">"""
        html_content_one += """<div id="storageicon" class="icon">-</div> Storage</a><ul id="storage-info-submenu" style="display: block">"""
        for i in range(len(storage_section)):
            storagename = storage_section[i][0]
            html_content_one += f'<div class="menuItem" onclick="toggleContent(\'{storagename}\', this)"><div class="icon">+</div> {storagename}</div>'
        html_content_one += "</ul></li><hr>"

    if worker_section:
        html_content_one += """<li><a href="#" onclick="showContentWorker(event, 'worker')" style="color: #00857e">"""
        html_content_one += """<div id="workericon" class="icon">-</div> Workers</a><ul id="worker-info-submenu" style="display: block">"""

        max_workers_to_display = min(len(worker_section), 5)
        for i in range(len(worker_section)):
            workername = worker_section[i][0]
            if i < max_workers_to_display:
                html_content_one += f'<div class="menuItem" onclick="toggleContent(\'worker-{i}\', this)"><div class="icon">+</div> {workername}</div>'
            else:
                html_content_one += f'<div class="menuItem hidden" onclick="toggleContent(\'worker-{i}\', this)"><div class="icon">+</div> {workername}</div>'

        if len(worker_section) > 5:
            html_content_one += """<button id="show-worker" onClick="showMoreWorker()">Show More</button>"""

        html_content_one += "</ul></li>"

    html_content_one += """</ul></div><div class="content" id="content-maxheight">"""

    # controller-0
    html_content_one += """<div id="controller-0">"""
    for i in controller_zero:
        html_content_one += f'{i}'
        html_content_one += "<br>"
    html_content_one += "<br></div>"

    for section_type, section_list in sections.items():
        for i, section in enumerate(section_list):
            if section_type == "controller":
                div_id = f"{section_type}-{i + 1}"
            else:
                div_id = f"{section_type}-{i}"
            html_content_one += f'<div id="{div_id}" style="display:none">'
            for j in section:
                html_content_one += f'{j}<br>'
            html_content_one += "<br></div>"

    html_content_one += "</div></div><br>"""
    return html_content_one


def html_result(log_contents, output_dir):
    """result part generation in the menu-content style
    generates correlated results, plugin results, and the items under them
    subitems for plugins and correlated results under separate menus

    Parameters:
    log_contents (string): content of the summary
    output_dir (string): the location of output
    """
    # Extract sections from the log
    plugin_section = extract_section(log_contents, 'Plugin Results:')
    correlated_section = extract_section(log_contents, 'Correlated Results:')

    # Process the extracted sections
    plugin_section = process_section(plugin_section, 'Plugin Results:')
    correlated_section = process_section(correlated_section, 'Correlated Results:')

    # HTML part
    correlated_directory = os.path.join(os.getcwd(), output_dir)
    os.chdir(correlated_directory)
    correlated_items = []
    for file in os.listdir(correlated_directory):
        if os.path.isfile(file) and '.' not in file:
            correlated_items.append({'name': file, 'id': f'content-item-{file}'})

    plugin_directory = os.path.join(correlated_directory, 'plugins')
    os.chdir(plugin_directory)

    plugin_items = []
    for file in os.listdir(plugin_directory):
        if os.path.isfile(file) and file != "system_info":
            plugin_items.append({'name': file, 'id': f'content-item-{file}'})

    html_content_two = ""

    html_content_two += """
    <div class="container-menu">
        <div class="menu">
        <ul>
        <li>
        <a href="#" onclick="toggleMenu(event, 'correlated-results-submenu')" class="menuTitle"> <span id="correlated-results-toggle" onclick="toggleSub(event, 'correlated-results-submenu', 'correlated-results-toggle')">- </span>
        Correlated Results</a>
            <ul id="correlated-results-submenu" style="display: block">"""

    for item in correlated_items:
        html_content_two += f'<li><a href="#" class="toggle-sign" onclick="showContentTwo(event, \'{item["id"]}\')">{item["name"]}</a></li>'

    html_content_two += """ </ul>
        </li>
        <hr>
        <li>
        <a href="#" onclick="toggleMenu(event, 'plugin-results-submenu')" class="menuTitle"> <span id="plugin-results-toggle" onclick="toggleSub(event, 'plugin-results-submenu', 'plugin-results-toggle')">+ </span>
        Plugin Results</a>
        <ul id="plugin-results-submenu" style="display: none">"""

    for item in plugin_items:
        html_content_two += f'<li><a href="#" class="toggle-sign" onclick="showContentTwo(event, \'{item["id"]}\')">{item["name"]}</a></li>'

    html_content_two += """</ul></li></ul></div>"""
    html_content_two += """<div class="content">"""

    for item in correlated_items:
        html_content_two += f'<div class="content-itemtwo" id="{item["id"]}"><h2>{item["name"].capitalize()}</h2><iframe src="{item["name"]}"></iframe></div>'

    for item in plugin_items:
        html_content_two += f'<div class="content-itemtwo" id="{item["id"]}"><h2>{item["name"].capitalize()}</h2><iframe src="plugins/{item["name"]}"></iframe></div>'

    html_content_two += f'<div class="content-itemtwo" id="content-item-correlated_results" style="display:block"><h2>Correlated Results</h2><textarea>{correlated_section}</textarea></div>'
    html_content_two += f'<div class="content-itemtwo" id="content-item-plugin_results"><h2>Plugin Results</h2><textarea>{plugin_section}</textarea></div>'
    html_content_two += """
    </div>
    </div>
    </body>
    """

    return html_content_two


# main
def main(input_dir, output_dir):
    reportlog_path = os.path.join(output_dir, 'report.log')
    with open(reportlog_path, 'r') as file:
        log_contents = file.read()

    sysinfo_path = os.path.join(output_dir, 'plugins/system_info')
    with open(sysinfo_path, 'r') as file:
        sysinfo_contents = file.read()

    # pre-set html file path
    html_file = os.path.abspath(os.path.join(output_dir, 'index.html'))

    sys_section = sysinfo_contents.strip().split("\n\n")
    html_content = html_css() + html_info(sys_section) + html_result(log_contents, output_dir) + html_script()
    html_content = html_content.format()

    # write the HTML content to file
    with open(html_file, "w") as file:
        file.write(html_content)
