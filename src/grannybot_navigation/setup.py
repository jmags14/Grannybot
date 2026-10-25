from setuptools import setup

package_name = "grannybot_navigation"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/grannybot_navigation"]),
        ("share/grannybot_navigation", ["package.xml"]),
        ("share/grannybot_navigation/config", ["config/rooms.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="Patrol, go-to-room and approach-person behaviors on top of Nav2",
    license="MIT",
    entry_points={
        "console_scripts": [
            "nav_commander = grannybot_navigation.nav_commander_node:main"
        ],
    },
)
