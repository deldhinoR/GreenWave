using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace GreenWaveAPI.Domain.Entities;

public class TrafficInput
{
    public int Id { get; set; }

    public int JunctionId { get; set; }

    public DateTime ReceivedTime { get; set; }

    public DateTime SavedTime { get; set; }

    public ICollection<Road> Roads { get; set; } = new List<Road>();
}

