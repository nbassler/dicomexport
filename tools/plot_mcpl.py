import sys
import mcpl
import matplotlib.pyplot as plt


def main(args=None) -> int:

    if args is None:
        args = sys.argv[1:]

    if len(args) != 1:
        print("Usage: python plot_mcpl.py <mcpl_file>")
        return 1

    # Load the MCPL file from command line argument
    m = mcpl.MCPLFile(args[0])

    # Extract particle positions (in mm)
    x, y = [], []
    for p in m.particles:
        x.append(p.x * 10.0)  # Convert cm to mm
        y.append(p.y * 10.0)

    # Create a 2D scatter plot
    fig, ax = plt.subplots(figsize=(5.9055, 5.9055))  # 15 cm x 15 cm canvas (1 cm = 0.393701 in)
    ax.scatter(x, y, s=1, alpha=0.5)

    # Labels and title
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_title('Particle Positions from MCPL File (X-Y Plane)')

    # show major grid lines
    ax.grid(which='major', linestyle='--', linewidth=0.5)

    # Optionally, set axis limits if you know the range
    # ax.set_xlim(0, 150)  # Uncomment and adjust if needed
    # ax.set_ylim(0, 150)

    plt.tight_layout()
    plt.show()
    return 0


if __name__ == '__main__':
    sys.exit(main())
