using GreenWaveAPI.Application.DTOs;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace GreenWaveAPI.Application.Interfaces;

public interface ISumoService
{
    Task SendToSumoAsync(SumoTrafficDto data);
}