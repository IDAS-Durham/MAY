#!/bin/bash
: '
This script takes all the python files in the may program, and creates a .md file with

# Name

::: path.to.file
    options:
        docstring_style: google


The program skips any files that already have been made.


COMMON ERROR:
If the package involved does not have an __init__.py in the folder (i.e. it is a native namespace), the Griffe package used by mkdocstrings will not render any files within it.
One should delete the relevant .md files, OR, create a __init__.py file in that folder. 
'

# Clean up temporary files
rm temp.txt temp2.txt


# Find all .py files
filelist=$(find ../may -name "*.py")

# Loop through the .py files
for f in $filelist;do
    fname=$(echo $f | awk '{print $NF}' FS=/)
    
    # If it isn't an __init__.py file
    if ! [ "$fname" = __init__.py ];then

	# Create the new file path with .md at the end
	newfpath=docs/may/$(echo $f | awk '{print $NF}' FS=may/ | rev | sed 's/yp./dm./' | rev)
	echo $newfpath
# 	# If the file doesn't already exist
	if ! [ -e "${newfpath}" ];then
	    # Create the file path, but in the python style (with . as seperators instead of /)
	    python_file_path=$(echo ${f} | sed 's/\//./g' | rev | sed 's/yp.//' | rev | cut --complement -c 1-3)
	    title=$(echo ${fname} | rev | cut --complement -c 1-3 | rev | sed 's/_/ /g')
	    
	    # Make the file
	    echo "# ${title^}

::: ${python_file_path}
    options:
      docstring_style: google
" > temp.txt
	    
	    # Copy the template into the .md file, and make any parent directories needed.
	    parent_dir=$(echo "${newfpath}" | awk 'BEGIN{FS=OFS="/"}{NF--; print}')

	    #install -Dv -m 666 temp.txt docs/${newfname}
	    mkdir -pv ${parent_dir}
	    cp -v temp.txt ${newfpath}
	    
	    # log the .md file path for the mkdocs.yml
	    echo "      - ${title^}: ${newfpath}" >> temp_potential_nav_additions.yml
#	else
#	    echo "Skipping docs/${newfname} as it already exists"
	fi
    fi
done


morefiles=$(find ../world_map -name "*.py")
# Loop through the .py files
for f in $morefiles;do
    fname=$(echo $f | awk '{print $NF}' FS=/)
    
    # If it isn't an __init__.py file
    if ! [ "$fname" = __init__.py ];then

	# Create the new file path with .md at the end
	newfpath=docs/world_map/$(echo $f | awk '{print $NF}' FS=world_map/ | rev | sed 's/yp./dm./' | rev)
	echo $newfpath
	# If the file doesn't already exist
	if ! [ -e "${newfpath}" ];then
	    # Create the file path, but in the python style (with . as seperators instead of /)
	    python_file_path=$(echo ${f} | sed 's/\//./g' | rev | sed 's/yp.//' | rev | cut --complement -c 1-3)
	    title=$(echo ${fname} | rev | cut --complement -c 1-3 | rev | sed 's/_/ /g')
	    
	    # Make the file
	    echo "# ${title^}

::: ${python_file_path}
    options:
      docstring_style: google
" > temp.txt
	    
	    # Copy the template into the .md file, and make any parent directories needed.
	    parent_dir=$(echo "${newfpath}" | awk 'BEGIN{FS=OFS="/"}{NF--; print}')

	    #install -Dv -m 666 temp.txt docs/${newfname}
	    mkdir -pv ${parent_dir}
	    cp -v temp.txt ${newfpath}
	    
	    # log the .md file path for the mkdocs.yml
	    echo "      - ${title^}: ${newfpath}" >> temp_potential_nav_additions.yml
#	else
#	    echo "Skipping docs/${newfname} as it already exists"
	fi
    fi
done



rm temp.txt temp2.txt
echo "
--------------------------------------------
Potential mkdocs.yml -nav section additions:
--------------------------------------------
"
cat temp_potential_nav_additions.yml

echo "
----------------------------------------
Find in temp_potential_nav_additions.yml
----------------------------------------"
