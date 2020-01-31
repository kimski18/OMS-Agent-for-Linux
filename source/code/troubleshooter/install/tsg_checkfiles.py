import os
import re
import subprocess

from tsg_info      import tsginfo_lookup
from tsg_errors    import tsg_error_info
from .tsg_checkoms import comp_versions_ge



# get files/directories/links from data files

def get_data(f, variables, files, links, dirs):
    curr_section = None
    with open(f, 'r') as data_file:
        for line in data_file:
            line = line.rstrip('\n')
            # skip comments
            cstart = line.find('#')
            if (cstart != -1):
                line = line[:cstart]

            # skip empty lines
            if (line == ''):
                continue            

            # new section
            if (line.startswith('%')):
                curr_section = line[1:]
                continue

            # line contains variable, needs to be replaced with content
            while ('${{' in line):
                vstart = line.index('${{')
                vend = line.index('}}') + 2
                l = line[vstart:vend]
                v = line[vstart+3:vend-2]
                if (v in list(variables.keys())):
                    line = line.replace(l, variables[v])
                else:
                    break

            # variable line
            if (curr_section == "Variables"):
                # parsed_line: [variable name, content]
                parsed_line = (line.replace(' ','')).split(':')
                variables[parsed_line[0]] = (parsed_line[1]).strip("'")
                continue

            # dependencies line
            elif (curr_section == "Dependencies"):
                pass
                # TODO: go through dependencies, make sure that currently running the version that works with it

            # file line
            elif (curr_section == "Files"):
                # parsed_line: [filepath, install filepath, permissions, user, group]
                parsed_line = (line.replace(' ','')).split(';')
                files[parsed_line[0]] = parsed_line[2:5]
                continue

            # link line
            elif (curr_section == "Links"):
                # parsed_line: [filepath, install filepath, permissions, user, group]
                parsed_line = (line.replace(' ','')).split(';')
                links[parsed_line[0]] = parsed_line[2:5] + [parsed_line[1]]
                continue

            # directory line
            elif (curr_section == "Directories"):
                # parsed_line: [filepath, permissions, user, group]
                parsed_line = (line.replace(' ','')).split(';')
                dirs[parsed_line[0]] = parsed_line[1:4]
                continue

            # installation code
            else:
                # check for changes in owners or permissions
                if (line.startswith('chmod ')):
                    # parsed_line: ['chmod', (recursive,) new permissions, filepath]
                    parsed_line = line.split()
                    path = parsed_line[-1]
                    # skip over anything with undefined variables
                    if (not path.startswith('/')):
                        continue
                    new_perms = parsed_line[-2]
                    if (parsed_line[1] == '-R'):
                        # recursively apply new perms
                        for f in (files.keys()):
                            if (f.startswith(path)):
                                files[f][0] = new_perms
                        for l in (links.keys()):
                            if (l.startswith(path)):
                                links[l][0] = new_perms
                        for d in (dirs.keys()):
                            if (d.startswith(path)):
                                dirs[d][0]  = new_perms
                    else: # not recursive
                        if path in files:
                            files[path][0] = new_perms
                        elif path in links:
                            links[path][0] = new_perms
                        elif path in dirs:
                            dirs[path][0]  = new_perms




# Convert between octal permission and symbolic permission
def perm_oct_to_symb(p):
    binstr = ''
    for i in range(3):
        binstr += format(int(p[i]), '03b')
    symbstr = 'rwxrwxrwx'
    result = ''
    for j in range(9):
        if (binstr[j] == '0'):
            result += '-'
        else:
            result += symbstr[j]
    return result

def perm_symb_to_oct(p):
    binstr = ''
    for i in range(9):
        if (p[i] == '-'):
            binstr += '0'
        else:
            binstr += '1'
    result = ''
    for j in range(0,9,3):
        result += str(int(binstr[j:j+3], 2))
    return result



# Check permissions are correct for each file
# info: [permissions, user, group]
def check_permissions(f, perm_info, corr_info, typ, perms_err):
    success = 0
    # check user
    perm_user = perm_info[1]
    corr_user = corr_info[1]
    if ((perm_user != corr_user) and (perm_user != 'omsagent')):
        perms_err.append((typ, f, 'user', perm_user, corr_user))
        success = 115
    
    # check group
    perm_group = perm_info[2]
    corr_group = corr_info[2]
    if ((perm_group != corr_group) and (perm_group != 'omiusers')):
        perms_err.append((typ, f, 'group', perm_group, corr_group))
        success = 115
    
    # check permissions
    perms = (perm_info[0])[1:].rstrip('.')
    corr_perms = perm_oct_to_symb(corr_info[0])
    if (perms != corr_perms):
        perms_err.append((typ, f, 'permissions', perms, corr_perms))
        success = 115
    return success
    


# Check directories exist

def get_ll_dir(ll_output, d):
    ll_lines = ll_output.split('\n')
    d_end = os.path.basename(d)
    ll_line = list(filter(lambda x : x.endswith(' ' + d_end), ll_lines))[0]
    return ll_line.split()

def check_dirs(dirs, exist_err, perms_err):
    success = 0
    missing_dirs = []
    for d in (dirs.keys()):
        if (any(d.startswith(md) for md in missing_dirs)):
            # parent folder doesn't exist, skip checking child folder
            continue
        # check if folder exists
        elif (not os.path.isdir(d)):
            missing_dirs += d
            exist_err.append(('directory', d))
            success = 114
            continue
        # check if permissions are correct
        if (success != 114):
            # get permissions
            ll_output = subprocess.check_output(['ls', '-l', os.path.join(d, '..')],\
                            universal_newlines=True)
            # ll_info: [perms, items, user, group, size, month mod, day mod, time mod, name]
            ll_info = get_ll_dir(ll_output, d)
            perm_info = [ll_info[0]] + ll_info[2:4]
            corr_info = dirs[d]
            if (check_permissions(d, perm_info, corr_info, "directory", perms_err) != 0):
                success = 115
    return success



# Check files exist

def check_files(files, exist_err, perms_err):
    success = 0
    for f in (files.keys()):
        # check if file exists
        if (not os.path.isfile(f)):
            exist_err.append(('file', f))
            success = 114
            continue
        # check if permissions are correct
        if (success != 114):
            # get permissions
            ll_output = subprocess.check_output(['ls', '-l', f], universal_newlines=True)
            # ll_info: [perms, items, user, group, size, month mod, day mod, time mod, name]
            ll_info = ll_output.split()
            perm_info = [ll_info[0]] + ll_info[2:4]
            corr_info = files[f]
            if (check_permissions(f, perm_info, corr_info, "file", perms_err) != 0):
                success = 115
    return success

            



# Check links exist

def check_links(links, exist_err, perms_err):
    success = True
    for l in (links.keys()):
        # check if link exists
        if (not os.path.islink(l)):
            exist_err.append(('link', l))
            success = 114
            continue
        # check if permissions are correct
        if (success != 114):
            linked_file = links[l][-1]
            # in case a link points to a link
            while (os.path.islink(linked_file)):
                linked_file = links[linked_file][-1]
            # get permissions
            if (os.path.isdir(linked_file)):
                ll_output = subprocess.check_output(['ls', '-l', os.path.join(linked_file, '..')],\
                                universal_newlines=True)
                ll_info = get_ll_dir(ll_output, linked_file)
            elif (os.path.isfile(linked_file)):
                ll_output = subprocess.check_output(['ls', '-l', linked_file],\
                                universal_newlines=True)
                ll_info = ll_output.split()
            # ll_info: [perms, items, user, group, size, month mod, day mod, time mod, name]
            perm_info = [ll_info[0]] + ll_info[2:4]
            corr_info = links[l][:-1]
            if (check_permissions(l, perm_info, corr_info, "link", perms_err) != 0):
                success = 115
    return success





# Check everything

def check_filesystem():
    success = 0

    dfs_path = "files/datafiles"  # path to datafiles from troubleshooter

    # create lists to track errors
    exist_err = []
    perms_err = []

    datafiles = os.listdir(dfs_path)
    for df in datafiles:
        # skip if wrong distro
        if (tsginfo_lookup('OS_READABLE_ID') == 'rhel' and df == 'wid_files_ubuntu.data'):
            continue
        if (tsginfo_lookup('OS_READABLE_ID') == 'ubuntu' and df == 'wid_files_redhat.data'):
            continue
        
        variables = dict()  # {var name : content}
        files = dict()      # {path : [perms, user, group]}
        links = dict()      # {path : [perms, user, group, linked path]}
        dirs = dict()       # {path : [perms, user, group]}

        # TEMP FIX: add in variables for RUBY_ARCH and RUBY_ARCM
        if (df.endswith("ruby.data")):
            variables['RUBY_ARCH'] = 'x86_64-linux'
            variables['RUBY_ARCM'] = 'x86_64-linux'

        # TEMP FIX: look for specific directory if in linux_rpm.data
        if ((df == "linux_rpm.data") and (not os.path.exists('/usr/sbin/semodule'))):
            continue

        # getting workspace id for protected files
        if (df.startswith("wid_files_")):
            variables['WORKSPACE_ID'] = tsginfo_lookup('WORKSPACE_ID')

        # populate dictionaries with info from data files
        get_data((os.path.join(dfs_path, df)), variables, files, links, dirs)

        # check everything
        checked_dirs = check_dirs(dirs, exist_err, perms_err)
        checked_files = check_files(files, exist_err, perms_err)
        checked_links = check_links(links, exist_err, perms_err)

        # some paths are missing
        if (114 in [checked_dirs, checked_files, checked_links]):
            success = 114

        # some paths have incorrect permissions
        elif ((115 in [checked_dirs, checked_files, checked_links]) and (success != 114)):
            success = 115

    # update errors
    if (success == 114):
        tsg_error_info.extend(exist_err)
    elif (success == 115):
        tsg_error_info.extend(perms_err)

    return success