########################################################################
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the Render function.
# The Rendering tool visualizes the collect bundle and generates
# an index.html file
#
########################################################################

from datetime import datetime
import os
from pathlib import Path
import re


def exclude_path():
    """Generate a set for files to be excluded

    """
    exclude_file = Path(__file__).parent / 'render.exclude'
    exclude_paths = set()
    if exclude_file.exists():
        with exclude_file.open('r') as file:
            exclude_paths = set(line.strip() for line in file)
    return exclude_paths


def can_open_file(file_path):
    """Test if the file can be opened or not empty

    Parameters:
    file_path(Path): path of the file
    """
    try:
        with open(file_path, 'r'):
            return os.path.getsize(file_path) != 0
    except IOError:
        return False


def extract_section(log_contents, start_phrase):
    """Extract the correlated or plugin content of the summary

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
    """Remove timestamp of summary message

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
    """Remove 'INFO' text of summary message

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
    """Return text with timestamp and INFO: removed

    Parameters:
    section (string): the message of the correlated/plugins section
    title (string): correlated/plugin results
    """
    section = section[len(title):]
    section = remove_timestamp(section)
    section = remove_emptyinfo(section)
    return section


def classify_node(data):
    """Classify node type in system_info summary

    Parameters:
    data (string): the summary of system_info
    """
    node_type = ''
    for item in data:
        if 'Node Type' in item:
            node_type = item.split(':')[-1].strip().lower()
    return node_type


def controller_sort(x):
    """Sort the controller, place the controller-0 first

    Parameters:
    x (list): list of controller info
    """
    return x[0] != 'controller-0'


def html_css():
    """Static css code of the rendering tool

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
                grid-template-columns: 25% auto 1fr;
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
                font-family: Courier;
                display: block;
                padding: 6px 10px;
            }}

            .menuTitle {{
                font-weight: bold;
                font-family: Courier;
                color: #00857e !important;
            }}

            .menuItem {{
                cursor: pointer;
                display: flex;
            }}

            .resizer {{
                width: 10px;
                background: #ccc;
                cursor: ew-resize;
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

            .content-item, .content-itemtwo, .content-itemthree {{
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

            .caret {{
                cursor: pointer;
                user-select: none;
                color: #00857e;
                font-weight: bold;
                font-family: Courier;
            }}

            .caret::before {{
                content: '+';
                color: #2F4F4F;
                margin-right: 6px;
            }}

            .caret-down::before {{
                color: #2F4F4F;
                content: '-';
            }}

            .text-color {{
              color: #00ada4;
            }}

            .nested {{ display: none; }}
            .active {{ display: block; }}

        </style>
    </head>
    """
    return html_content_css


def html_script():
    """Static script code

    Functions:
    toggleContent: show content in System Info section
    toggleSub: show/hide submenus in correlated/plugin results
    toggleMenu: show the correlated/plugin summary
    showContentStorage: display content of selected storage item
    showContentWorker: display content of selected worker item
    showContentTwo: display content of result section
    toggleTree: show the collect bundle
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

    function showContentThree(event, contentId) {{
        event.preventDefault();

        const contentItems = document.querySelectorAll('.content-itemthree');
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

    function toggleTree() {{
        var toggler = document.getElementsByClassName('caret');
        for (var i = 0; i < toggler.length; i++) {{
            var nested = toggler[i].parentElement.querySelector('.nested');
            var isEmpty = nested.querySelectorAll('li').length === 0;

            if (!isEmpty) {{
                toggler[i].addEventListener('click', function() {{
                    this.parentElement.querySelector('.nested').classList.toggle('active');
                    this.classList.toggle('caret-down');
                    this.parentElement.classList.toggle('text-color');
                }});
            }} else {{
                toggler[i].style.color = '#808080';
            }}
        }}
    }}

    // Call the function when the page loads to initialize the tree behavior
    toggleTree();

    document.addEventListener("DOMContentLoaded", function() {{
    var hash = window.location.hash;
    var sectionA = document.getElementById('content-one');
    var sectionB = document.getElementById('content-two');
    var sectionC = document.getElementById('content-three');
    var collectSections = document.querySelectorAll('[id*="collect"]');

    collectSections.forEach(function(section) {{
        section.classList.add('hidden');
    }});

    sectionC.classList.add('hidden');

    if (hash.includes("collect")) {{
        sectionA.classList.add('hidden');
        sectionB.classList.add('hidden');
        sectionC.classList.remove('hidden');
        var matchingElement = document.querySelector(hash);
        if (matchingElement) {{
            matchingElement.classList.remove('hidden');
        }}
    }}
    }});

    document.addEventListener("DOMContentLoaded", function() {{
        const containers = document.querySelectorAll('.container-menu');

        containers.forEach(container => {{
            const resizer = container.querySelector('.resizer');
            let startX, startWidth;

            resizer.addEventListener('mousedown', function(e) {{
                startX = e.clientX;
                startWidth = container.querySelector('.menu').offsetWidth;
                document.addEventListener('mousemove', handleMouseMove);
                document.addEventListener('mouseup', stopResize);
            }});

            function handleMouseMove(e) {{
                let currentWidth = startWidth + e.clientX - startX;
                container.style.gridTemplateColumns = `${currentWidth}px auto 1fr`;
            }}

            function stopResize() {{
                document.removeEventListener('mousemove', handleMouseMove);
                document.removeEventListener('mouseup', stopResize);
            }}
        }});
    }});

    window.onload = function() {{
        var hash = window.location.hash;
        if (hash.includes("collect")) {{
            document.title = hash.substring(8, hash.length - 14);
        }}
    }};

    </script>
    </html>
    """
    return html_content_script


def html_info(sys_section):
    """System info part generation
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
    <div id="content-one" class="container-menu">
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

    html_content_one += """</ul></div><div class="resizer"></div><div class="content" id="content-maxheight">"""

    # controller-0
    html_content_one += """<div id="controller-0">"""
    for i in controller_zero:
        html_content_one += f'{i}'.replace(' ', '&nbsp;')
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
                html_content_one += f'{j}'.replace(' ', '&nbsp;')
                html_content_one += "<br>"
            html_content_one += "<br></div>"

    html_content_one += "</div></div><br>"""
    return html_content_one


def html_result(log_contents, output_dir):
    """Result part generation in the menu-content style
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
    <div id="content-two" class="container-menu">
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

    html_content_two += "</ul></li><hr>" + generate_collect() + "</ul></div><div class='resizer'></div>"
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
    """

    return html_content_two


def generate_collect():
    os.chdir('../../')
    current_directory = Path('.')
    finalstr = """<li><a href="#" class="menuTitle">
        <span id="bundle-toggle" onclick="toggleSub(event, 'bundle-submenu', 'bundle-toggle')">+ </span>
        Collect Bundle</a><ul id="bundle-submenu" style="display: none">"""
    for item in current_directory.iterdir():
        if item.is_dir() and item.name != "report_analysis":
            temp_item = re.sub(r'[^a-zA-Z0-9]', '', item.name)
            finalstr += f'<a href="#collect{temp_item}" target="_blank">{item.name}</a>'
    finalstr += "</ul></li>"
    return finalstr


def html_collect():
    """Collect bundle code generation

    Calls a helper function to to generate the collect bundle
    """
    current_directory = Path('.')
    tree_html = ""
    content_html = "<div class='content'>"
    target_dir = current_directory.resolve()
    newtree_html, newcontent_html = generate_directory_tree(current_directory, exclude_path(), target_dir, 0)
    tree_html += newtree_html
    content_html += newcontent_html
    content_html += "</div>"
    html_content_three = """<div class="container-menu" id="content-three"><div class="menu" style="max-height: 90vh">
        """ + tree_html + "</div><div class='resizer'></div>" + content_html + "</div></body>"
    return html_content_three


def generate_directory_tree(directory_path, exclude_path, target_dir, is_top_level):
    """Helper function for Collect bundle generation

    Parameters:
    directory_path(Path): the path of the directory in each call
    target_dir(string): the path of the file/folder
    is_top_level(bool): if the level is the top level of the collect bundle
    """
    directory_name = directory_path.name
    tree_html = ""
    content_html = ""
    approved_list = ['.log', '.conf', '.info', '.json', '.alarm', '.pid', '.list', '.lock', '.txt']
    if is_top_level == 1:
        temp_name = re.sub(r'[^a-zA-Z0-9]', '', directory_name)
        tree_html = f'<li id=collect{temp_name}><div class="menuTitle">{directory_name}</div><ul>'
    if is_top_level > 1:
        tree_html = f'<li><span class="caret">{directory_name}</span><ul class="nested">'
    for item in directory_path.iterdir():
        # write to a file called 'exclude', all the files including the full path
        # if item in exclude, do not add to html
        # else add it to another
        item_path = str(item)
        if not any(exclude_item in item_path for exclude_item in exclude_path):
            try:
                if item.is_dir() and item.name != "report_analysis":
                    nested_tree_html, nested_content_html = generate_directory_tree(item, exclude_path, target_dir, is_top_level + 1)
                    tree_html += nested_tree_html
                    content_html += nested_content_html
                elif item.is_file():
                    if not can_open_file(item):
                        tree_html += f'<li><a style="color: #808080">{item}</a></li>'
                    else:
                        if item.name.endswith(tuple(approved_list)):
                            tree_html += f'<li><a href="#" class="toggle-sign" onclick="showContentThree(event, \'{item}\')">{item.name}</a></li>'
                            content_html += f'<div class="content-itemthree" id="{item}"><h2>{item.name}</h2><iframe src="{target_dir}/{item}"></iframe></div>'
                        else:
                            if not item.name.endswith(".tgz") and not item.name.endswith(".gz"):
                                tree_html += f'<li><a href="../{item}" target="_blank">{item}</a></li>'
            # if it's permission error, just skip reading the file or folder
            except PermissionError as e:
                continue
    if is_top_level:
        tree_html += '</ul></li>'

    return tree_html, content_html


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
    html_content = html_css() + html_info(sys_section) + html_result(log_contents, output_dir)
    html_content = html_content.format()
    html_content += html_collect() + html_script()

    # write the HTML content to file
    with open(html_file, "w") as file:
        file.write(html_content)
