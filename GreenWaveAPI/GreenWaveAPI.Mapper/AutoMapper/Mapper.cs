using AutoMapper;
using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Features.Traffic.Commands;
using GreenWaveAPI.Domain.Entities;

namespace GreenWaveAPI.Mapper.AutoMapper
{
    public class TrafficMappingProfile : Profile
    {
        public TrafficMappingProfile()
        {
            CreateMap<CreateTrafficCommandRequest, TrafficInput>()
                .ForMember(dest => dest.Id, opt => opt.Ignore())
                .ForMember(dest => dest.ReceivedTime,
                           opt => opt.MapFrom(src => DateTime.UtcNow))
                .ForMember(dest => dest.SavedTime,
                           opt => opt.Ignore()) 
                .ForMember(dest => dest.Roads,
                           opt => opt.MapFrom(src => src.Roads));
        }
    }
}
