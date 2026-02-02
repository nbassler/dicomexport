import mcpl
import matplotlib.pyplot as plt

# Load the MCPL file
m = mcpl.MCPLFile("myoutput_field01.mcpl")

# Extract particle positions (in mm)
x, y = [], []
for p in m.particles:
    x.append(p.x)
    y.append(p.y)

# Create a 2D scatter plot
fig, ax = plt.subplots(figsize=(5.9055, 5.9055))  # 15 cm x 15 cm canvas (1 cm = 0.393701 in)
ax.scatter(x, y, s=1, alpha=0.5)

# Labels and title
ax.set_xlabel('X (mm)')
ax.set_ylabel('Y (mm)')
ax.set_title('Particle Positions from MCPL File (X-Y Plane)')

# Optionally, set axis limits if you know the range
# ax.set_xlim(0, 150)  # Uncomment and adjust if needed
# ax.set_ylim(0, 150)

plt.tight_layout()
plt.show()
